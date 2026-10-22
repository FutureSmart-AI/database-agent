SELECT c.customer_id, COUNT(q.order_id) AS order_count, SUM(q.net_cents) AS net_cents
FROM customers c LEFT JOIN qualified q ON q.customer_id = c.customer_id
WHERE c.active = 1 GROUP BY c.customer_id ORDER BY c.customer_id;
