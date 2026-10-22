WITH item_totals AS (
    SELECT order_id, SUM(amount_cents) AS gross_cents FROM items GROUP BY order_id
), refund_totals AS (
    SELECT order_id, SUM(amount_cents) AS refund_cents FROM refunds
    WHERE refunded_on < '2026-02-01' GROUP BY order_id
), qualified AS (
    SELECT o.order_id, o.customer_id, c.region,
           i.gross_cents - COALESCE(r.refund_cents, 0) AS net_cents
    FROM orders o JOIN customers c ON c.customer_id = o.customer_id
    JOIN item_totals i ON i.order_id = o.order_id
    LEFT JOIN refund_totals r ON r.order_id = o.order_id
    WHERE c.active = 1 AND o.status = 'completed' AND o.currency = 'USD'
      AND o.ordered_on >= '2026-01-01' AND o.ordered_on < '2026-02-01'
)
