SELECT o.currency, SUM(i.amount_cents) AS gross_cents FROM orders o
JOIN customers c ON c.customer_id = o.customer_id JOIN items i ON i.order_id = o.order_id
WHERE c.active = 1 AND o.status = 'completed'
  AND o.ordered_on >= '2026-01-01' AND o.ordered_on < '2026-02-01'
GROUP BY o.currency ORDER BY o.currency;
