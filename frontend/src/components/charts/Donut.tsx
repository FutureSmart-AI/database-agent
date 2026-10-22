"use client";

import { Cell, Pie, PieChart } from "recharts";

import { DONUT_SIZE } from "./constants";

export interface DonutSegment {
  value: number;
  color: string;
  name?: string;
}

interface DonutProps {
  segments: DonutSegment[];
  /** Text in the middle — usually the headline percentage or total. */
  center: string;
}

/**
 * 80×80 donut, drawn with recharts like the agent UI's service breakdown, with
 * the headline figure sitting in the hole.
 *
 * Sized in pixels rather than wrapped in a `ResponsiveContainer`: the box never
 * changes size, and measuring it meant every donut in a breakdown table logged
 * recharts' `width(-1) and height(-1)` warning on mount and carried its own
 * resize observer for no benefit.
 */
export default function Donut({ segments, center }: DonutProps) {
  const data = segments.filter((segment) => segment.value > 0);

  return (
    <div className="relative size-20">
      <PieChart width={DONUT_SIZE} height={DONUT_SIZE}>
        <Pie
          data={data.length ? data : [{ value: 1, color: "#e2e8f0" }]}
          dataKey="value"
          nameKey="name"
          innerRadius={25}
          outerRadius={35}
          startAngle={90}
          endAngle={-270}
          stroke="none"
          isAnimationActive={false}
        >
          {(data.length ? data : [{ value: 1, color: "#e2e8f0" }]).map(
            (segment, index) => (
              <Cell key={index} fill={segment.color} />
            ),
          )}
        </Pie>
      </PieChart>
      <span className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-900">
        {center}
      </span>
    </div>
  );
}
