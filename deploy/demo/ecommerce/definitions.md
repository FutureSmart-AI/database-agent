# Cedar Lane: sample e-commerce database

The database behind the free "Try with sample data" agent on the hosted Database Agent.
Cedar Lane is a made-up US online shop. Every row is synthetic, generated from one fixed seed
by `build.py`; emails use the reserved `example.com` domain.

Calendar year 2025 only, so no answer depends on today's date.

| Table | Rows | What it holds |
|---|---:|---|
| `categories` | 8 | Product categories |
| `products` | 120 | Catalogue: `list_price`, `unit_cost`, category |
| `customers` | 2,400 | `segment` (consumer, business), `acquisition_channel`, city, state |
| `orders` | 4,950 | `status`, `channel`, `subtotal`, `discount_amount`, `shipping_fee`, `total_amount` |
| `order_items` | 8,689 | Product, `quantity`, `unit_price`, `line_total` |
| `payments` | 4,858 | Payment attempts: `method`, `status` (captured, failed) |
| `returns` | 482 | Return requests per order item: `reason`, `status`, `refund_amount` |

Built-in patterns, so questions have something to find: a holiday peak in November and
December, a growing customer base through the year, Apparel returned far more often than
other categories (mostly "wrong size"), business customers ordering in larger quantities, and
customers from email and referrals ordering more often.

## Business definitions

These are also the agent's table descriptions (`agent.json`), so the agent and the reference
answers use the same definitions.

- **Order value:** `orders.total_amount = subtotal - discount_amount + shipping_fee`, in US dollars.
- **Cancelled orders:** never paid. They are excluded from revenue, spend and order value.
- **Revenue:** `SUM(total_amount)` of orders whose status is not `cancelled`, dated by `ordered_at`.
- **Customer total spend:** `SUM(total_amount)` of the customer's non-cancelled orders.
- **Average order value:** `AVG(total_amount)` of non-cancelled orders.
- **Payment-method share:** captured payments by method, as a percent of all captured payments.
  Each non-cancelled order has exactly one captured payment.
- **Return rate:** approved returns divided by order items on delivered orders, as a percent.
- **Gross margin of a sale:** `(order_items.unit_price - products.unit_cost) * quantity`.

## Reference answers

`reference_answers.json` holds the answer to each suggested question, computed in plain
Python from the generated rows. `check_references.py` runs each answer's `reference_sql` on
the loaded database and requires exactly the same rows, so every answer is confirmed by two
independent computations. `provision.py database` runs that check as the read-only role.

## Rebuild

```bash
python build.py references reference_answers.json
DEMO_ADMIN_DSN=... DEMO_READER_PASSWORD=... python provision.py database --replace
```

`provision.py agent` creates the shared agent; `provision.py descriptions` re-applies the
business definitions to an existing one. Both wait for the automatic description job that
adding a database starts, then write the definitions and read them back (DA-DESC-RACE-001).

The reader role `sample_ecommerce_reader` has `SELECT` on this database's tables and no other
table privileges on the cluster (it can open a connection to another database but read nothing), has
read-only transactions by default, a 15-second statement timeout and at most 20 connections.
`provision.py` proves `DELETE`, `UPDATE`, `CREATE TABLE` and `DROP TABLE` are refused.
