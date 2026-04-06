"""
Catalog API routes — Products, Quotations, and Invoices.

All routes require authentication. Prefix: /api
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_active_user
from saas.database import get_db
from saas.models import Invoice, Lead, Product, Quotation, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Catalog"])

CurrentUser = Depends(get_current_active_user)


# ─── Pydantic schemas ────────────────────────────────────────────────────────


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    unit: str = Field(default="piece", max_length=20)
    base_price: float = Field(..., ge=0)
    gst_rate: float = Field(default=18.0, ge=0, le=100)
    image_url: Optional[str] = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    unit: Optional[str] = None
    base_price: Optional[float] = Field(None, ge=0)
    gst_rate: Optional[float] = Field(None, ge=0, le=100)
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class LineItem(BaseModel):
    product_id: Optional[str] = None
    name: str
    qty: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    gst_rate: float = Field(default=18.0, ge=0, le=100)
    unit: str = "piece"


class QuotationCreate(BaseModel):
    lead_id: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    buyer_email: Optional[str] = None
    buyer_phone: Optional[str] = None
    buyer_city: Optional[str] = None
    items: list[LineItem] = []
    notes: Optional[str] = None
    valid_until: Optional[datetime] = None


class QuotationStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(draft|sent|accepted|rejected)$")


class InvoiceCreate(BaseModel):
    quotation_id: Optional[str] = None
    lead_id: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    buyer_email: Optional[str] = None
    buyer_phone: Optional[str] = None
    buyer_city: Optional[str] = None
    items: list[LineItem] = []
    due_date: Optional[datetime] = None


class PaymentStatusUpdate(BaseModel):
    payment_status: str = Field(..., pattern=r"^(unpaid|partial|paid)$")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _calc_totals(items: list[LineItem]) -> tuple[float, float, float]:
    """Returns (subtotal, gst_amount, total_amount)."""
    subtotal = 0.0
    gst_total = 0.0
    for item in items:
        line_subtotal = item.qty * item.unit_price
        gst = line_subtotal * (item.gst_rate / 100)
        subtotal += line_subtotal
        gst_total += gst
    return round(subtotal, 2), round(gst_total, 2), round(subtotal + gst_total, 2)


def _items_to_json(items: list[LineItem]) -> str:
    data = []
    for item in items:
        line_subtotal = round(item.qty * item.unit_price, 2)
        gst = round(line_subtotal * (item.gst_rate / 100), 2)
        data.append({
            "product_id": item.product_id,
            "name": item.name,
            "qty": item.qty,
            "unit": item.unit,
            "unit_price": item.unit_price,
            "gst_rate": item.gst_rate,
            "line_subtotal": line_subtotal,
            "gst_amount": gst,
            "total": round(line_subtotal + gst, 2),
        })
    return json.dumps(data)


async def _next_quotation_number(db: AsyncSession, user_id: str) -> str:
    year = datetime.now(timezone.utc).year
    result = await db.execute(
        select(func.count(Quotation.id))
        .where(Quotation.user_id == user_id)
    )
    count = result.scalar_one() or 0
    return f"QT-{year}-{count + 1:04d}"


async def _next_invoice_number(db: AsyncSession, user_id: str) -> str:
    year = datetime.now(timezone.utc).year
    result = await db.execute(
        select(func.count(Invoice.id))
        .where(Invoice.user_id == user_id)
    )
    count = result.scalar_one() or 0
    return f"INV-{year}-{count + 1:04d}"


def _product_dict(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "hsn_code": p.hsn_code, "unit": p.unit, "base_price": p.base_price,
        "gst_rate": p.gst_rate, "image_url": p.image_url, "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _quotation_dict(q: Quotation) -> dict:
    return {
        "id": q.id, "quotation_number": q.quotation_number,
        "lead_id": q.lead_id, "status": q.status,
        "buyer_name": q.buyer_name, "buyer_company": q.buyer_company,
        "buyer_email": q.buyer_email, "buyer_phone": q.buyer_phone,
        "buyer_city": q.buyer_city,
        "items": json.loads(q.items_json or "[]"),
        "subtotal": q.subtotal, "gst_amount": q.gst_amount, "total_amount": q.total_amount,
        "notes": q.notes,
        "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        "created_at": q.created_at.isoformat() if q.created_at else None,
    }


def _invoice_dict(inv: Invoice) -> dict:
    return {
        "id": inv.id, "invoice_number": inv.invoice_number,
        "lead_id": inv.lead_id, "quotation_id": inv.quotation_id,
        "payment_status": inv.payment_status,
        "buyer_name": inv.buyer_name, "buyer_company": inv.buyer_company,
        "buyer_email": inv.buyer_email, "buyer_phone": inv.buyer_phone,
        "buyer_city": inv.buyer_city,
        "items": json.loads(inv.items_json or "[]"),
        "subtotal": inv.subtotal, "gst_amount": inv.gst_amount, "total_amount": inv.total_amount,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


def _generate_document_html(
    doc_type: str,  # "QUOTATION" or "INVOICE"
    number: str,
    buyer_name: str,
    buyer_company: str,
    buyer_email: str,
    buyer_phone: str,
    buyer_city: str,
    items: list[dict],
    subtotal: float,
    gst_amount: float,
    total_amount: float,
    seller_name: str,
    seller_company: str,
    notes: str = "",
    extra_label: str = "",
    extra_value: str = "",
) -> str:
    """Generate a professional HTML document for download."""
    rows = ""
    for i, item in enumerate(items, 1):
        rows += f"""
        <tr>
            <td>{i}</td>
            <td><strong>{item.get('name', '')}</strong><br><small style="color:#666">{item.get('product_id', '') and 'SKU: ' + item.get('product_id', '')[:8] or ''}</small></td>
            <td style="text-align:center">{item.get('qty', 0)} {item.get('unit', 'pcs')}</td>
            <td style="text-align:right">₹{item.get('unit_price', 0):,.2f}</td>
            <td style="text-align:center">{item.get('gst_rate', 0)}%</td>
            <td style="text-align:right">₹{item.get('gst_amount', 0):,.2f}</td>
            <td style="text-align:right"><strong>₹{item.get('total', 0):,.2f}</strong></td>
        </tr>"""

    extra_row = f"<tr><td colspan='2'><strong>{extra_label}</strong></td><td colspan='5'>{extra_value}</td></tr>" if extra_label else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{doc_type} — {number}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; color: #1a1a2e; background: #fff; padding: 40px; max-width: 900px; margin: auto; }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; padding-bottom: 24px; border-bottom: 3px solid #e94560; }}
  .brand {{ font-size: 22px; font-weight: 800; color: #1a1a2e; }}
  .brand span {{ color: #e94560; }}
  .doc-meta {{ text-align: right; }}
  .doc-type {{ font-size: 28px; font-weight: 800; color: #e94560; letter-spacing: 2px; }}
  .doc-num {{ font-size: 15px; color: #555; margin-top: 4px; }}
  .parties {{ display: flex; gap: 40px; margin-bottom: 28px; }}
  .party {{ flex: 1; background: #f8f9fa; border-radius: 10px; padding: 16px; }}
  .party h4 {{ font-size: 11px; text-transform: uppercase; color: #e94560; letter-spacing: 1px; margin-bottom: 8px; }}
  .party .name {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; }}
  .party .detail {{ color: #555; font-size: 12px; line-height: 1.6; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th {{ background: #1a1a2e; color: #fff; padding: 10px 12px; text-align: left; font-size: 12px; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  .totals {{ margin-left: auto; width: 320px; margin-top: 16px; }}
  .totals table {{ margin: 0; }}
  .totals td {{ padding: 8px 12px; border: none; }}
  .totals .grand-total td {{ background: #1a1a2e; color: #fff; font-weight: 700; font-size: 15px; border-radius: 6px; }}
  .notes {{ margin-top: 28px; padding: 16px; background: #fff9f0; border-left: 4px solid #e94560; border-radius: 4px; }}
  .notes h4 {{ font-size: 12px; color: #e94560; text-transform: uppercase; margin-bottom: 6px; }}
  .footer {{ margin-top: 40px; text-align: center; color: #aaa; font-size: 11px; border-top: 1px solid #eee; padding-top: 20px; }}
  @media print {{ body {{ padding: 20px; }} }}
  @media (max-width: 600px) {{ .parties {{ flex-direction: column; }} .header {{ flex-direction: column; gap: 16px; }} }}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="brand">Lead<span>Flow</span></div>
    <div style="color:#888;font-size:12px;margin-top:4px;">AI-Powered CRM Platform</div>
  </div>
  <div class="doc-meta">
    <div class="doc-type">{doc_type}</div>
    <div class="doc-num"># {number}</div>
    <div class="doc-num">Date: {datetime.now(timezone.utc).strftime('%d %b %Y')}</div>
  </div>
</div>

<div class="parties">
  <div class="party">
    <h4>From (Seller)</h4>
    <div class="name">{seller_name or 'Your Business'}</div>
    <div class="detail">{seller_company or ''}</div>
  </div>
  <div class="party">
    <h4>To (Buyer)</h4>
    <div class="name">{buyer_name or '—'}</div>
    <div class="detail">
      {buyer_company or ''}<br>
      {buyer_city or ''}<br>
      {buyer_email or ''}<br>
      {buyer_phone or ''}
    </div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>#</th><th>Item / Description</th><th>Qty</th><th>Unit Price</th><th>GST</th><th>GST Amt</th><th>Total</th>
    </tr>
  </thead>
  <tbody>
    {rows}
    {extra_row}
  </tbody>
</table>

<div class="totals">
  <table>
    <tr><td>Subtotal</td><td style="text-align:right">₹{subtotal:,.2f}</td></tr>
    <tr><td>GST Amount</td><td style="text-align:right">₹{gst_amount:,.2f}</td></tr>
    <tr class="grand-total"><td>Grand Total</td><td style="text-align:right">₹{total_amount:,.2f}</td></tr>
  </table>
</div>

{"<div class='notes'><h4>Notes</h4><p>" + notes + "</p></div>" if notes else ""}

<div class="footer">
  Generated by LeadFlow CRM · {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}
</div>

<script>window.onload = function() {{ /* Auto-print: window.print(); */ }};</script>
</body>
</html>"""


# ─── Product Routes ──────────────────────────────────────────────────────────


@router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    active_only: bool = False,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(Product).where(Product.user_id == user.id)
    if active_only:
        query = query.where(Product.is_active == True)
    if search:
        query = query.where(Product.name.ilike(f"%{search}%"))
    query = query.order_by(Product.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page)
    products = (await db.execute(query)).scalars().all()

    return {
        "products": [_product_dict(p) for p in products],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    product = Product(
        user_id=user.id,
        name=body.name,
        description=body.description,
        hsn_code=body.hsn_code,
        unit=body.unit,
        base_price=body.base_price,
        gst_rate=body.gst_rate,
        image_url=body.image_url,
        is_active=body.is_active,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return _product_dict(product)


@router.put("/products/{product_id}")
async def update_product(
    product_id: str,
    body: ProductUpdate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.user_id == user.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(product, field, val)

    await db.commit()
    await db.refresh(product)
    return _product_dict(product)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.user_id == user.id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.delete(product)
    await db.commit()
    return {"success": True, "message": "Product deleted"}


# ─── Quotation Routes ────────────────────────────────────────────────────────


@router.get("/quotations")
async def list_quotations(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(Quotation).where(Quotation.user_id == user.id)
    if status_filter:
        query = query.where(Quotation.status == status_filter)
    query = query.order_by(Quotation.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page)
    quotations = (await db.execute(query)).scalars().all()

    return {
        "quotations": [_quotation_dict(q) for q in quotations],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/quotations/from-lead/{lead_id}")
async def quotation_from_lead(
    lead_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pre-fill buyer details from a lead."""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {
        "lead_id": lead.id,
        "buyer_name": lead.sender_name,
        "buyer_company": lead.sender_company,
        "buyer_email": lead.sender_email,
        "buyer_phone": lead.sender_mobile,
        "buyer_city": lead.sender_city,
    }


@router.post("/quotations", status_code=status.HTTP_201_CREATED)
async def create_quotation(
    body: QuotationCreate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Validate lead if provided
    if body.lead_id:
        lead_res = await db.execute(
            select(Lead).where(Lead.id == body.lead_id, Lead.user_id == user.id)
        )
        if not lead_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Lead not found")

    subtotal, gst_amount, total_amount = _calc_totals(body.items)
    items_json = _items_to_json(body.items)
    q_number = await _next_quotation_number(db, user.id)

    quotation = Quotation(
        user_id=user.id,
        lead_id=body.lead_id,
        quotation_number=q_number,
        buyer_name=body.buyer_name,
        buyer_company=body.buyer_company,
        buyer_email=body.buyer_email,
        buyer_phone=body.buyer_phone,
        buyer_city=body.buyer_city,
        items_json=items_json,
        subtotal=subtotal,
        gst_amount=gst_amount,
        total_amount=total_amount,
        notes=body.notes,
        valid_until=body.valid_until,
        status="draft",
    )
    db.add(quotation)
    await db.commit()
    await db.refresh(quotation)
    return _quotation_dict(quotation)


@router.get("/quotations/{quotation_id}")
async def get_quotation(
    quotation_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Quotation).where(Quotation.id == quotation_id, Quotation.user_id == user.id)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    return _quotation_dict(q)


@router.put("/quotations/{quotation_id}/status")
async def update_quotation_status(
    quotation_id: str,
    body: QuotationStatusUpdate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Quotation).where(Quotation.id == quotation_id, Quotation.user_id == user.id)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    q.status = body.status
    await db.commit()
    return {"success": True, "status": q.status}


@router.post("/quotations/{quotation_id}/send")
async def send_quotation(
    quotation_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Quotation).where(Quotation.id == quotation_id, Quotation.user_id == user.id)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    q.status = "sent"
    await db.commit()
    return {"success": True, "message": "Quotation marked as sent", "status": "sent"}


@router.get("/quotations/{quotation_id}/pdf", response_class=HTMLResponse)
async def quotation_pdf(
    quotation_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Quotation).where(Quotation.id == quotation_id, Quotation.user_id == user.id)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")

    items = json.loads(q.items_json or "[]")
    valid_until_str = q.valid_until.strftime('%d %b %Y') if q.valid_until else "—"

    html = _generate_document_html(
        doc_type="QUOTATION",
        number=q.quotation_number,
        buyer_name=q.buyer_name or "",
        buyer_company=q.buyer_company or "",
        buyer_email=q.buyer_email or "",
        buyer_phone=q.buyer_phone or "",
        buyer_city=q.buyer_city or "",
        items=items,
        subtotal=q.subtotal,
        gst_amount=q.gst_amount,
        total_amount=q.total_amount,
        seller_name=user.name,
        seller_company=user.company_name or "",
        notes=q.notes or "",
        extra_label="Valid Until",
        extra_value=valid_until_str,
    )
    from fastapi.responses import HTMLResponse as HR
    return HR(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="quotation-{q.quotation_number}.html"'},
    )


# ─── Invoice Routes ──────────────────────────────────────────────────────────


@router.get("/invoices")
async def list_invoices(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    payment_status: Optional[str] = Query(None),
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(Invoice).where(Invoice.user_id == user.id)
    if payment_status:
        query = query.where(Invoice.payment_status == payment_status)
    query = query.order_by(Invoice.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page)
    invoices = (await db.execute(query)).scalars().all()

    return {
        "invoices": [_invoice_dict(inv) for inv in invoices],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # If quotation_id provided, copy from quotation
    if body.quotation_id:
        q_res = await db.execute(
            select(Quotation).where(Quotation.id == body.quotation_id, Quotation.user_id == user.id)
        )
        q = q_res.scalar_one_or_none()
        if not q:
            raise HTTPException(status_code=404, detail="Quotation not found")

        inv_number = await _next_invoice_number(db, user.id)
        invoice = Invoice(
            user_id=user.id,
            lead_id=q.lead_id,
            quotation_id=q.id,
            invoice_number=inv_number,
            buyer_name=q.buyer_name,
            buyer_company=q.buyer_company,
            buyer_email=q.buyer_email,
            buyer_phone=q.buyer_phone,
            buyer_city=q.buyer_city,
            items_json=q.items_json,
            subtotal=q.subtotal,
            gst_amount=q.gst_amount,
            total_amount=q.total_amount,
            due_date=body.due_date,
            payment_status="unpaid",
        )
    else:
        if body.lead_id:
            lead_res = await db.execute(
                select(Lead).where(Lead.id == body.lead_id, Lead.user_id == user.id)
            )
            if not lead_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Lead not found")

        subtotal, gst_amount, total_amount = _calc_totals(body.items)
        items_json = _items_to_json(body.items)
        inv_number = await _next_invoice_number(db, user.id)

        invoice = Invoice(
            user_id=user.id,
            lead_id=body.lead_id,
            invoice_number=inv_number,
            buyer_name=body.buyer_name,
            buyer_company=body.buyer_company,
            buyer_email=body.buyer_email,
            buyer_phone=body.buyer_phone,
            buyer_city=body.buyer_city,
            items_json=items_json,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total_amount=total_amount,
            due_date=body.due_date,
            payment_status="unpaid",
        )

    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return _invoice_dict(invoice)


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_dict(inv)


@router.put("/invoices/{invoice_id}/payment")
async def update_payment_status(
    invoice_id: str,
    body: PaymentStatusUpdate,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv.payment_status = body.payment_status
    await db.commit()
    return {"success": True, "payment_status": inv.payment_status}


@router.get("/invoices/{invoice_id}/pdf", response_class=HTMLResponse)
async def invoice_pdf(
    invoice_id: str,
    user: User = CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user.id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    items = json.loads(inv.items_json or "[]")
    due_str = inv.due_date.strftime('%d %b %Y') if inv.due_date else "—"

    html = _generate_document_html(
        doc_type="INVOICE",
        number=inv.invoice_number,
        buyer_name=inv.buyer_name or "",
        buyer_company=inv.buyer_company or "",
        buyer_email=inv.buyer_email or "",
        buyer_phone=inv.buyer_phone or "",
        buyer_city=inv.buyer_city or "",
        items=items,
        subtotal=inv.subtotal,
        gst_amount=inv.gst_amount,
        total_amount=inv.total_amount,
        seller_name=user.name,
        seller_company=user.company_name or "",
        extra_label="Due Date",
        extra_value=due_str,
    )
    from fastapi.responses import HTMLResponse as HR
    return HR(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="invoice-{inv.invoice_number}.html"'},
    )
