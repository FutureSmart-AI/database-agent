import { Fragment, type ReactNode } from "react";

/**
 * SQL highlighter.
 *
 * One pass over the raw SQL, emitting each token as its own node — nothing is
 * re-scanned, so a keyword inside a string literal stays a string. Token colours
 * are Tailwind utilities in the agent UI's palette.
 */
const KEYWORDS =
  "SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|LEFT JOIN|INNER JOIN|RIGHT JOIN|FULL JOIN|JOIN|ON|AS|AND|OR|NOT|IN|IS|NULL|DESC|ASC|HAVING|WITH|CASE|WHEN|THEN|ELSE|END|BETWEEN|DISTINCT|UNION ALL|UNION|OVER|PARTITION BY|INTERVAL|EXTRACT|FILTER|COALESCE|OFFSET";

const FUNCTIONS =
  "COUNT|SUM|AVG|MIN|MAX|ROUND|DATE_TRUNC|NOW|CAST|LOWER|UPPER|RANK|ROW_NUMBER|LAG|ABS|NULLIF|CONCAT";

const TOKEN = new RegExp(
  `(--[^\\n]*)|('(?:[^']|'')*')|(\\b(?:${FUNCTIONS})\\b(?=\\s*\\())|(\\b(?:${KEYWORDS})\\b)|(\\b\\d+(?:\\.\\d+)?\\b)`,
  "gi",
);

/** comment · string · function · keyword · number */
const TOKEN_CLASS = {
  c: "text-slate-400 italic",
  s: "text-emerald-600",
  f: "text-violet-600",
  k: "font-semibold text-indigo-600",
  n: "text-amber-600",
} as const;

export function highlightSql(sql: string | null | undefined): ReactNode {
  const source = String(sql ?? "");
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  const token = new RegExp(TOKEN.source, TOKEN.flags);

  for (let match = token.exec(source); match; match = token.exec(source)) {
    if (match.index > last) nodes.push(source.slice(last, match.index));
    const kind = match[1]
      ? "c"
      : match[2]
        ? "s"
        : match[3]
          ? "f"
          : match[4]
            ? "k"
            : "n";
    nodes.push(
      <span key={`t${key++}`} className={TOKEN_CLASS[kind]}>
        {match[0]}
      </span>,
    );
    last = match.index + match[0].length;
  }
  if (last < source.length) nodes.push(source.slice(last));

  return <Fragment>{nodes}</Fragment>;
}
