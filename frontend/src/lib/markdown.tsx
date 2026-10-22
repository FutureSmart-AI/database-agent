import { Fragment, type ReactNode } from "react";

import { TABLE } from "./tableStyles";

/**
 * The answer-body markdown subset the design artifact renders: `**bold**`,
 * `` `code` ``, GFM tables, blockquotes and paragraphs. Nothing else — answers
 * come from the model as this subset, and keeping the renderer this small means
 * no HTML is ever interpolated (React escapes every text node for us).
 */

function inline(text: string): ReactNode {
  // Split on **bold** and `code`, keeping the delimiters so they can be mapped
  // to elements. Both are non-nesting in this subset.
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return (
    <Fragment>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code
              key={index}
              className="rounded border border-slate-200 bg-slate-100 px-1 py-px font-mono text-[0.9em]"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </Fragment>
  );
}

const cells = (row: string) =>
  row
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((cell) => cell.trim());

/** True when a cell should be right-aligned — numeric, ignoring $ , * decoration. */
const isNumeric = (cell: string, columnIndex: number) =>
  columnIndex > 0 &&
  cell !== "" &&
  !Number.isNaN(Number.parseFloat(cell.replace(/[$,*]/g, "")));

export function markdown(source: string | null | undefined): ReactNode {
  const lines = String(source ?? "").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    // Table: a pipe row followed by a divider row.
    if (
      /^\s*\|/.test(line) &&
      /^\s*\|[\s\-:|]+\|\s*$/.test(lines[index + 1] ?? "")
    ) {
      const head = cells(line);
      index += 2;
      const body: string[][] = [];
      while (index < lines.length && /^\s*\|/.test(lines[index])) {
        body.push(cells(lines[index]));
        index++;
      }
      blocks.push(
        <div
          key={blocks.length}
          className={`${TABLE.wrap} my-3 rounded-lg border border-gray-200`}
        >
          <table className={TABLE.table}>
            <thead>
              <tr className={TABLE.headRow}>
                {head.map((heading, i) => (
                  <th key={i} className={TABLE.th}>
                    {inline(heading)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, rowIndex) => (
                <tr key={rowIndex} className={TABLE.row}>
                  {row.map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className={
                        isNumeric(cell, cellIndex) ? TABLE.tdNumeric : TABLE.td
                      }
                    >
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      blocks.push(
        <div
          key={blocks.length}
          className="my-2 border-l-2 border-slate-200 pl-3 text-slate-500 italic"
        >
          {inline(line.replace(/^\s*>\s?/, ""))}
        </div>,
      );
      index++;
      continue;
    }

    if (line.trim() === "") {
      index++;
      continue;
    }

    blocks.push(
      <p key={blocks.length} className="mb-2.5 last:mb-0">
        {inline(line)}
      </p>,
    );
    index++;
  }

  return <Fragment>{blocks}</Fragment>;
}
