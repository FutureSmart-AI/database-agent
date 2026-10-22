import type { ChipTone } from "@/components/ui/Chip";
import type { QueryGroup } from "@/data/reports";

export const EMPTY_REPORT: {
  name: string;
  instructions: string;
  analysis: string;
  schedule: string;
  groups: QueryGroup[];
} = {
  name: "",
  instructions: "",
  analysis: "",
  schedule: "none",
  groups: [{ type: "independent", queries: [""] }],
};

export const STATUS_TONE: Record<string, ChipTone> = {
  completed: "green",
  running: "blue",
  pending: "slate",
  queued: "slate",
  cancelled: "amber",
  failed: "rose",
};

export const QUERY_VERDICT: Record<string, { label: string; tone: ChipTone }> =
  {
    pass: { label: "Pass", tone: "green" },
    weak: { label: "Weak", tone: "amber" },
    fail: { label: "Fail", tone: "rose" },
    pending: { label: "Pending", tone: "slate" },
  };
