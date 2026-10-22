SELECT (SELECT COUNT(*) FROM customers WHERE active = 1) AS population,
       (SELECT COUNT(DISTINCT customer_id) FROM qualified) AS converters, ROUND(AVG(rate), 2) AS conversion_percent
FROM (SELECT 100.0 * COUNT(DISTINCT q.customer_id) / COUNT(DISTINCT c.customer_id) AS rate
      FROM customers c LEFT JOIN qualified q ON q.customer_id = c.customer_id
      WHERE c.active = 1 GROUP BY c.region) regional;
