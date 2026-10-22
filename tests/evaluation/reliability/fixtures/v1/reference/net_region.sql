SELECT region, SUM(net_cents) AS net_cents FROM qualified GROUP BY region ORDER BY region;
