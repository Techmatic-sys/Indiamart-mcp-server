# 🛠️ MCP Tools Reference

Detailed documentation for all IndiaMART MCP Server tools.

---

## get_leads_by_date_tool

Fetch leads from IndiaMART for a specific date range and save them to the local database.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | ✅ | Start date (formats: `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD-Mon-YYYY`) |
| `end_date` | string | ✅ | End date (same formats as above) |

**Returns:** Formatted markdown table with lead summaries (name, product, city, time). Shows up to 30 leads.

**Example:**
```
"Show me all leads from March 1 to March 25, 2026"
→ Calls get_leads_by_date_tool(start_date="2026-03-01", end_date="2026-03-25")
```

---

## get_recent_leads_tool

Get leads from the last N hours. Automatically syncs from IndiaMART API first, then returns results from the local database.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `hours` | int | ❌ | 24 | Number of hours to look back |

**Returns:** Numbered list of leads with name, product, phone, email, city, time, and message preview.

**Example:**
```
"Show me leads from the last 12 hours"
→ Calls get_recent_leads_tool(hours=12)
```

---

## search_leads_tool

Search the local database for leads matching a keyword in product name or message content.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `keyword` | string | ✅ | Search term (minimum 2 characters) |

**Returns:** Numbered list of matching leads (up to 50) with ID, name, product, phone, city, and message preview.

**Example:**
```
"Find all leads asking about steel pipes"
→ Calls search_leads_tool(keyword="steel pipes")
```

---

## get_lead_by_id_tool

Get complete details of a specific lead by its unique query ID.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query_id` | string | ✅ | The `UNIQUE_QUERY_ID` of the lead |

**Returns:** Full lead details including name, company, all contact info, address, product, subject, message, query type, and timestamps.

**Example:**
```
"Show me the full details of lead IML123456789"
→ Calls get_lead_by_id_tool(query_id="IML123456789")
```

---

## export_leads_csv_tool

Export leads from the local database as a CSV string for a given date range.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | ✅ | Start date (same formats as get_leads_by_date) |
| `end_date` | string | ✅ | End date |

**Returns:** CSV-formatted string with columns: unique_query_id, query_time, sender_name, sender_mobile, sender_email, sender_company, sender_city, sender_state, query_product_name, query_message, query_type, subject.

**Example:**
```
"Export all January 2026 leads as CSV"
→ Calls export_leads_csv_tool(start_date="2026-01-01", end_date="2026-01-31")
```

---

## sync_latest_leads_tool

Sync the latest leads from IndiaMART into the local database. Fetches the last 7 days of leads to ensure nothing is missed.

**Parameters:** None

**Returns:** Sync summary with counts of fetched, new, and duplicate leads.

**Example:**
```
"Sync my latest IndiaMART leads"
→ Calls sync_latest_leads_tool()
```

---

## get_lead_stats_tool

Get comprehensive lead statistics from the local database.

**Parameters:** None

**Returns:** Statistics including:
- Total leads in database
- Top 10 cities by lead count (with bar chart)
- Top 10 products by enquiry count (with bar chart)
- Daily lead counts for the last 7 days (with bar chart)

**Example:**
```
"How many leads did I get this week? Which cities are they from?"
→ Calls get_lead_stats_tool()
```

---

## draft_reply_tool

Draft a professional reply message for a buyer enquiry. Fetches the lead details and composes a personalized response.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query_id` | string | ✅ | The `UNIQUE_QUERY_ID` of the lead to reply to |
| `seller_name` | string | ✅ | Your name or business name |
| `product_info` | string | ✅ | Product details, pricing, or availability to include |

**Returns:** Formatted draft reply with metadata (recipient, product, query type) and the full reply text ready to copy-paste.

**Example:**
```
"Draft a reply for lead IML123456789. My business is Vasanth Industries. We offer SS304 pipes at ₹250/kg."
→ Calls draft_reply_tool(
    query_id="IML123456789",
    seller_name="Vasanth Industries",
    product_info="We offer SS304 pipes at ₹250/kg with free delivery for orders above 500kg."
  )
```
