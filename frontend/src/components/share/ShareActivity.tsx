"use client";

import { useMemo, useState } from "react";

import BarChart from "@/components/charts/BarChart";
import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import SearchInput from "@/components/ui/SearchInput";
import { RowsSkeleton } from "@/components/ui/Skeletons";
import TabNav from "@/components/ui/TabNav";
import {
  useSessions,
  useSessionTurns,
  type SessionRow,
} from "@/data/conversations";
import { useActivityQueries, type ActivityRow } from "@/data/shareActivity";
import { apiMessage } from "@/lib/apiError";
import { ago, ms } from "@/lib/format";
import { markdown } from "@/lib/markdown";
import { highlightSql } from "@/lib/sql";
import { TABLE } from "@/lib/tableStyles";
import { getHttpStatus } from "@/platform/analytics/utils";
import { Button, Select } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import {
  ANSWER_BUBBLE,
  AVATAR,
  QUESTION_BUBBLE,
} from "../conversations/constants";
import { ACTIVITY_RANGES } from "./constants";

/** Which store the list is reading: people you shared with, or the site bubble. */
type Segment = "users" | "widget";
type SortColumn = "who" | "title" | "asked" | "at";
type Sort = { column: SortColumn; desc: boolean };

/**
 * Who asked. The log carries the asker's id on a signed-in question and nothing
 * at all on a bubble one, so the fallback says which of the two it is rather
 * than printing an empty cell.
 */
const who = (row: ActivityRow) =>
  row.who ?? (row.fromWidget ? "Website visitor" : "Guest");

/**
 * A listed session that the query log did not account for.
 *
 * `from_chat_widget` is typed a boolean but the service leaves it off a
 * shared-user session, so it has to be read as one here: the segment filter
 * compares it with `===`, and an `undefined` that the tab badge counted (`!undefined`)
 * was dropped from both lists — "Nothing shared yet" under a badge saying 6.
 */
const fromSession = (session: SessionRow): ActivityRow => ({
  id: session.session_id,
  sessionId: session.session_id,
  who: session.user_id,
  fromWidget: Boolean(session.from_chat_widget),
  title:
    session.session_title || session.display_message || "Untitled conversation",
  asked: 0,
  at: Date.parse(session.created_time) || 0,
  latency: null,
});

/**
 * Share → Activity: everything other people asked this agent.
 *
 * The owner's own history stays under Conversations. This is the other side of
 * sharing — what the people you invited and the visitors on your website did
 * with it — which is why it lives on the Share screen rather than as a third
 * tab of somebody else's chat history. Opening a row is read-only by design:
 * there is no composer, because answering somebody else's question inside their
 * conversation is not a thing this product does.
 */
export default function ShareActivity({ agentId }: { agentId?: string }) {
  const [segment, setSegment] = useState<Segment>("users");
  const [query, setQuery] = useState("");
  const [range, setRange] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>({ column: "at", desc: true });

  const days = range === "all" ? null : Number(range);
  /**
   * The list is the query log, not the session list.
   *
   * `GET …/sessions` answers `{"sessions": []}` even for an agent asked a
   * question a moment ago, so a screen built on it alone showed "Nothing shared
   * yet" over conversations that plainly existed. The log is per answered
   * question and says who asked and whether it came from the bubble; the
   * session list is merged on top of it for anything it does return.
   */
  const activity = useActivityQueries(agentId, { days });
  const users = useSessions(agentId, "users");
  const widget = useSessions(agentId, "widget");

  /** Both stores, folded into one row per conversation. */
  const all = useMemo(() => {
    const rows = new Map<string, ActivityRow>();
    (activity.data?.rows ?? []).forEach((row) => rows.set(row.id, { ...row }));
    [...(users.data ?? []), ...(widget.data ?? [])].forEach((session) => {
      const existing = rows.get(session.session_id);
      if (!existing) {
        rows.set(session.session_id, fromSession(session));
        return;
      }
      // The log knows the questions; the session row knows the stored title and
      // can name an asker the log left null.
      existing.who = existing.who ?? session.user_id;
      existing.fromWidget = Boolean(
        existing.fromWidget || session.from_chat_widget,
      );
    });
    return [...rows.values()];
  }, [activity.data, users.data, widget.data]);

  const sessions = useMemo(
    () => all.filter((row) => row.fromWidget === (segment === "widget")),
    [all, segment],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const floor = days === null ? 0 : Date.now() - days * 864e5;
    const rows = sessions.filter(
      (row) =>
        row.at >= floor &&
        (!needle || `${who(row)} ${row.title}`.toLowerCase().includes(needle)),
    );
    const direction = sort.desc ? -1 : 1;
    return [...rows].sort((a, b) => {
      if (sort.column === "at") return (a.at - b.at) * direction;
      if (sort.column === "asked") return (a.asked - b.asked) * direction;
      const key = sort.column === "who" ? who : (row: ActivityRow) => row.title;
      return key(a).localeCompare(key(b)) * direction;
    });
  }, [days, query, sessions, sort]);

  const opened = all.find((row) => row.id === openId);
  const turns = useSessionTurns(agentId, opened?.sessionId ?? null);
  const filtering = Boolean(query.trim()) || range !== "all";
  /**
   * A brand-new agent 404s on the analytics routes — the documented first-run
   * state, not a failure, and the session list still answers. So a 404 here is
   * an empty log, and only a real error is reported.
   */
  const logError =
    activity.isError && getHttpStatus(activity.error) !== 404
      ? activity.error
      : null;
  const loading = activity.isLoading || users.isLoading || widget.isLoading;
  const failed = logError ?? (users.error || widget.error ? users.error : null);

  const sortable = (column: SortColumn, label: string, numeric = false) => (
    <th
      scope="col"
      aria-sort={
        sort.column === column
          ? sort.desc
            ? "descending"
            : "ascending"
          : "none"
      }
      className={cn(numeric ? TABLE.thNumeric : TABLE.th, "p-0")}
    >
      <button
        type="button"
        onClick={() =>
          setSort((previous) =>
            previous.column === column
              ? { column, desc: !previous.desc }
              : // A numeric column opens on its largest value: the busiest
                // conversation, or the most recent one.
                { column, desc: column === "at" || column === "asked" },
          )
        }
        className={cn(
          "flex w-full cursor-pointer items-center gap-1 px-4 py-2.5 uppercase",
          numeric && "justify-end",
          sort.column === column ? "text-slate-700" : "hover:text-slate-700",
        )}
      >
        {label}
        <Icon
          name="caretUpDown"
          className={cn(
            "size-3",
            sort.column === column ? "text-indigo-500" : "text-slate-300",
          )}
        />
      </button>
    </th>
  );

  if (opened) {
    return (
      <Card>
        <CardHeader
          title={
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate">{opened.title}</span>
            </span>
          }
          note={
            opened.fromWidget
              ? `${who(opened)} · from the chat bubble on your website`
              : `${who(opened)} · asked through your share link`
          }
          action={
            <Button
              variant="secondary"
              size="sm"
              startIcon={<Icon name="back" className="size-4" />}
              onClick={() => setOpenId(null)}
            >
              Back
            </Button>
          }
        />
        <CardBody className="space-y-5">
          {turns.isLoading ? (
            <RowsSkeleton rows={3} />
          ) : turns.error ? (
            <Banner tone="error">{apiMessage(turns.error)}</Banner>
          ) : !turns.data?.length ? (
            <EmptyState
              icon="chat"
              title="Nothing in this conversation"
              note="The session exists, but the service returned no messages for it."
            />
          ) : (
            turns.data.map((turn) => (
              <div key={turn.chat_id} className="flex flex-col gap-3">
                <div className="flex justify-end">
                  <div className={QUESTION_BUBBLE}>{turn.question}</div>
                </div>
                <div className="flex gap-3">
                  <span className={AVATAR}>
                    <Icon name="bot" className="size-5" />
                  </span>
                  <div className={ANSWER_BUBBLE}>
                    <div className="space-y-4 p-5">
                      <div className="text-sm leading-relaxed text-slate-700">
                        {markdown(turn.answer)}
                      </div>
                      {turn.chart && (
                        <div className="overflow-hidden rounded-lg border border-gray-200">
                          <div className="border-b border-gray-100 bg-slate-50 px-4 py-2.5 text-sm font-semibold text-slate-700">
                            {turn.chart.title}
                          </div>
                          <div className="p-4">
                            <BarChart
                              data={turn.chart.data}
                              title={turn.chart.title}
                            />
                          </div>
                        </div>
                      )}
                      {turn.sql && (
                        <details className="rounded-lg border border-gray-200">
                          <summary className="flex cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-slate-700">
                            Executed SQL
                            {turn.latency !== null && (
                              <span className="ml-auto">
                                <Chip tone="slate" size="sm">
                                  {ms(turn.latency)}
                                </Chip>
                              </span>
                            )}
                          </summary>
                          <div className="border-t border-gray-100 p-3">
                            <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-700">
                              {highlightSql(turn.sql)}
                            </pre>
                            {turn.tables.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {turn.tables.map((table) => (
                                  <Chip key={table} tone="blue" size="sm">
                                    {table}
                                  </Chip>
                                ))}
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                      {!turn.sql && (
                        <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-500">
                          No query was recorded for this answer, so there is
                          nothing to inspect here. Turn on{" "}
                          <span className="font-semibold">Show sources</span>{" "}
                          under Settings → Answers to keep the SQL with future
                          answers.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </CardBody>
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-3 text-center text-xs font-medium text-slate-500 sm:px-6">
          Read-only — this is someone else&apos;s conversation. Ask your own
          questions under Conversations.
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <TabNav<Segment>
        label="Activity source"
        activeTab={segment}
        onChange={(next) => {
          setSegment(next);
          setOpenId(null);
        }}
        tabs={[
          {
            key: "users",
            label: "Shared users",
            count: all.filter((row) => !row.fromWidget).length,
          },
          {
            key: "widget",
            label: "Widget",
            count: all.filter((row) => row.fromWidget).length,
          },
        ]}
      />
      <CardBody className="space-y-3">
        <p className="text-sm text-slate-500">
          {segment === "users"
            ? "Everything people who can reach this agent have asked. Your own questions stay under Conversations."
            : "Everything visitors asked through the chat bubble on your website."}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            className="min-w-44 flex-1 sm:max-w-80"
            label="Search activity"
            placeholder="Search person or question…"
            value={query}
            onChange={setQuery}
          />
          <Select
            size="sm"
            fullWidth={false}
            className="w-40"
            aria-label="Date range"
            value={range}
            onChange={setRange}
            options={ACTIVITY_RANGES.map(([value, label]) => ({
              value,
              label,
            }))}
          />
          {sessions.length > 0 && (
            <Chip tone="slate" size="sm">
              {filtered.length} of {sessions.length} shown
            </Chip>
          )}
        </div>
      </CardBody>
      {loading ? (
        <CardBody>
          <RowsSkeleton rows={4} />
        </CardBody>
      ) : failed ? (
        <CardBody>
          <Banner tone="error">{apiMessage(failed)}</Banner>
        </CardBody>
      ) : !filtered.length ? (
        <EmptyState
          icon={segment === "users" ? "users" : "code"}
          title={
            sessions.length
              ? "Nothing matches your filters"
              : segment === "users"
                ? "Nothing shared yet"
                : "Nothing from the bubble yet"
          }
          note={
            sessions.length
              ? `${sessions.length} conversation${
                  sessions.length === 1 ? "" : "s"
                } here, but none match the search or the date range.`
              : segment === "users"
                ? "No one has asked anything through your share link yet."
                : "No conversations from the website bubble yet."
          }
          action={
            filtering && sessions.length ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setQuery("");
                  setRange("all");
                }}
              >
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className={TABLE.wrap}>
          <table className={TABLE.table}>
            <thead>
              <tr className={TABLE.headRow}>
                {sortable("who", segment === "users" ? "Person" : "Visitor")}
                {sortable("title", "Conversation")}
                {sortable("asked", "Questions asked", true)}
                {sortable("at", "Last activity", true)}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                // Only a conversation the service can hand back can be opened;
                // a logged question with no session is listed, not clickable.
                const openable = Boolean(row.sessionId);
                return (
                  <tr
                    key={row.id}
                    tabIndex={openable ? 0 : undefined}
                    title={
                      openable
                        ? "Open this conversation, read-only"
                        : "The service has no thread for this question"
                    }
                    className={cn(TABLE.row, openable && "cursor-pointer")}
                    onClick={() => openable && setOpenId(row.id)}
                    onKeyDown={(event) => {
                      if (
                        openable &&
                        (event.key === "Enter" || event.key === " ")
                      ) {
                        event.preventDefault();
                        setOpenId(row.id);
                      }
                    }}
                  >
                    <td className={TABLE.td}>
                      <span className="font-medium text-slate-800">
                        {who(row)}
                      </span>
                    </td>
                    <td className={cn(TABLE.td, "max-w-[46ch] truncate")}>
                      {row.title}
                    </td>
                    <td className={TABLE.tdNumeric}>{row.asked || "—"}</td>
                    <td className={TABLE.tdNumeric}>
                      {row.at ? ago(row.at, Date.now()) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {activity.data?.truncated && (
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-2 text-xs text-slate-500 sm:px-6">
          Showing the most recent 100 questions — narrow the date range to see
          further back.
        </div>
      )}
    </Card>
  );
}
