SELECT c.customer_id, i.item_id FROM customers c CROSS JOIN items i ORDER BY c.customer_id, i.item_id;
