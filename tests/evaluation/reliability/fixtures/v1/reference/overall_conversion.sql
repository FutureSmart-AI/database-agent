SELECT COUNT(DISTINCT c.customer_id) AS population, COUNT(DISTINCT q.customer_id) AS converters,
       ROUND(100.0 * COUNT(DISTINCT q.customer_id) / COUNT(DISTINCT c.customer_id), 2) AS conversion_percent
FROM customers c LEFT JOIN qualified q ON q.customer_id = c.customer_id WHERE c.active = 1;
