# 💬 Example Conversations

Real-world usage examples for the IndiaMART MCP Server with Claude.

---

## 1. Morning Lead Check

**You:** "Good morning! Show me all leads I got yesterday."

**Claude:** *Uses `get_recent_leads_tool(hours=24)` to sync and display yesterday's leads.*

> 📬 **Recent Leads (last 24 hours)** — 5 total
> 1. **Rahul Sharma** — Stainless Steel Pipes
>    📱 9876543210 | 📧 rahul@example.com
>    🏙️ Mumbai | 🕐 2026-03-24 14:30:00
>    💬 I need 100 units of SS304 pipes, 2 inch diameter...
> ...

---

## 2. Finding Specific Leads

**You:** "Search for anyone asking about copper tubes."

**Claude:** *Uses `search_leads_tool(keyword="copper tubes")`*

> 🔍 **Search Results for 'copper tubes'** — 3 matches
> 1. [IML789456] **Vikram Singh** — Copper Tubes for AC Installation
> ...

---

## 3. Detailed Lead View + Reply

**You:** "Show me the full details of lead IML789456 and draft a reply. We're Vasanth Industries and we sell copper tubes at ₹450/meter."

**Claude:** *First calls `get_lead_by_id_tool(query_id="IML789456")`, then `draft_reply_tool(...)`*

> 📋 **Lead Details — IML789456**
> **Name:** Vikram Singh
> **Company:** Singh Cooling Solutions
> **Product:** Copper Tubes
> **Message:** Require 200 meters of copper tubes for AC installation project...
>
> ---
>
> ✉️ **Draft Reply for Lead IML789456**
>
> Dear Vikram Singh,
>
> Thank you for your enquiry regarding **Copper Tubes**...

---

## 4. Weekly Analytics

**You:** "Give me a summary of this week's leads — how many, from where, and what products."

**Claude:** *Uses `get_lead_stats_tool()`*

> 📊 **Lead Statistics**
>
> **Total Leads in Database:** 47
>
> **🏙️ Top Cities:**
>   Mumbai: 12 ████████████
>   Delhi: 8 ████████
>   Ahmedabad: 6 ██████
> ...

---

## 5. CSV Export for Team

**You:** "Export all leads from March 2026 as CSV so I can share with my sales team."

**Claude:** *Uses `export_leads_csv_tool(start_date="2026-03-01", end_date="2026-03-31")`*

> 📄 **CSV Export (47 leads, 2026-03-01 → 2026-03-31)**
> ```csv
> unique_query_id,query_time,sender_name,sender_mobile,...
> IML123456,2026-03-01 09:15:00,Rahul Sharma,9876543210,...
> ```

---

## 6. Quick Sync

**You:** "Sync my latest leads from IndiaMART."

**Claude:** *Uses `sync_latest_leads_tool()`*

> ✅ **Sync Complete**
> Fetched: 12 leads from IndiaMART
> New: 5 leads saved to database
> Duplicates skipped: 7

---

## 7. Date Range Query

**You:** "Show me all leads from January 15 to February 28, 2026."

**Claude:** *Uses `get_leads_by_date_tool(start_date="2026-01-15", end_date="2026-02-28")`*

> 📊 **Leads Report: 2026-01-15 → 2026-02-28**
> Total leads fetched: 89 (89 new, 0 already in DB)
> | # | Name | Product | City | Time |
> |---|------|---------|------|------|
> | 1 | Amit Kumar | MS Angles | Jaipur | 2026-01-15 11:20:00 |
> ...

---

## Tips for Best Results

1. **Be specific with dates** — Claude understands natural language dates but specific formats work best.
2. **Sync first** — If you haven't used the server in a while, ask Claude to sync before searching.
3. **Use lead IDs** — When you want details or replies, reference the specific lead ID from search results.
4. **Combine tools** — Ask Claude to "find leads about X and draft a reply for the most recent one" — it will chain tools automatically.
5. **Export regularly** — Use CSV export to maintain backups and share with your team.
