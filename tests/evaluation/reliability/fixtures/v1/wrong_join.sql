SELECT c.region, SUM(i.amount_cents - COALESCE(r.amount_cents, 0)) AS net_cents
FROM orders o JOIN customers c ON c.customer_id = o.customer_id
JOIN items i ON i.order_id = o.order_id
LEFT JOIN refunds r ON r.order_id = o.order_id AND r.refunded_on < '2026-02-01'
WHERE c.active = 1 AND o.status = 'completed' AND o.currency = 'USD'
  AND o.ordered_on >= '2026-01-01' AND o.ordered_on < '2026-02-01'
GROUP BY c.region ORDER BY c.region;
