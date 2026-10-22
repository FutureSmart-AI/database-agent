"use client";

import Link from "next/link";

import dayjs from "dayjs";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import { RowsSkeleton } from "@/components/ui/Skeletons";
import { useOwnerLimits, type LimitItem } from "@/data/usage";
import { apiMessage } from "@/lib/apiError";
import { nfmt } from "@/lib/format";
import { ROUTES } from "@/lib/routes";
import { cn } from "@/platform/utils";

/**
 * The Limits tab, from `GET /v1/owners/me/limits` — one read for the whole tab.
 *
 * Every judgement this panel used to make on the client is now resolved by the
 * service, and reading it rather than re-deriving it is the point:
 *
 * · `lifted` — an own-keys limit whose providers the owner already holds. It
 *   arrives with `percent: null` and is drawn with NO bar. A progress bar
 *   against a ceiling nobody is enforcing is a lie the reader can act on. The
 *   ceiling is still stated in words, so "lifted" never costs the reader sight
 *   of what the cap actually is.
 * · `limit: null` — no limit at all. The used figure and the words, never a 0%
 *   bar, which reads as "you are out" when nothing is capped.
 * · `enforced` — whether going over stops anything. Today that is
 *   `queries_per_day` alone; drawing any other row as a blocker invents a
 *   consequence that does not exist.
 * · `raises` — which route moves this ceiling: a tier change, the owner's own
 *   provider keys, or either.
 *
 * Neither the consumption-source control nor the period control applies here.
 * A limit is enforced against every request the platform served, whichever key
 * paid for it, and the window is fixed in `billing_window` — a ceiling anchored
 * to a window the reader can change is meaningless. Both controls are disabled
 * by `UsageView` while this tab is open.
 */

const PROVIDER_LABELS: Record<string, string> = {
  groq: "Groq",
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  deepseek: "DeepSeek",
  minimax: "MiniMax",
  langsmith: "LangSmith",
  aws: "AWS",
};

function providerLabel(key: string): string {
  return PROVIDER_LABELS[key] ?? key;
}

/** "Groq", "Groq and OpenAI", "Groq, OpenAI and Google". */
function joinList(values: string[]): string {
  if (values.length < 2) return values[0] ?? "";
  return `${values.slice(0, -1).join(", ")} and ${values[values.length - 1]}`;
}

/**
 * Whether this row's figure is money.
 *
 * The service sends the cost row's unit as `USD`, so the match is
 * case-insensitive — and a money figure carries its currency in the `$` already,
 * which is why `unitSuffix` drops the unit rather than printing "$3.80 USD".
 */
function isMoney(item: LimitItem): boolean {
  return item.key === "cost" || item.unit?.toLowerCase() === "usd";
}

/** Cost rows come back in dollars; everything else is a count. */
function formatUsed(item: LimitItem, value: number): string {
  if (isMoney(item)) return `$${value.toFixed(2)}`;
  return nfmt(value);
}

/** The unit, where the figure does not already say it. */
function unitSuffix(item: LimitItem): string {
  if (isMoney(item) || !item.unit) return "";
  return ` ${item.unit}`;
}

/**
 * The one line that says what would move this ceiling, and the buttons for it.
 *
 * Both routes are always offered on a limit that still applies, because either
 * one may be the reader's answer; a lifted limit offers neither, and says why.
 */
function EscapeRoute({ item }: { item: LimitItem }) {
  const held = (item.held ?? []).map(providerLabel);
  const missing = (item.missing ?? []).map(providerLabel);

  if (item.lifted) {
    return (
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Chip tone="green" size="sm">
          <Icon name="chk" className="size-3" />
          Lifted by your own {joinList(held)} key{held.length > 1 ? "s" : ""}
        </Chip>
        <Link
          href={ROUTES.credentials}
          className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
        >
          Manage credentials
        </Link>
        <p className="basis-full text-[11.5px] leading-relaxed text-slate-400">
          Nothing to raise while your own key is serving these requests. Remove
          that key and this limit comes back.
        </p>
      </div>
    );
  }

  const ownKeysHelp =
    missing.length > 0
      ? `Either raises this: a higher tier lifts the ceiling, or your own ${joinList(missing)} key${missing.length > 1 ? "s" : ""} removes it entirely.`
      : "Only a tier change raises this one — adding your own keys changes what you pay for, not this ceiling.";

  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-2">
      <Link
        href={ROUTES.credentials}
        className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
      >
        Add your credentials
      </Link>
      <p className="basis-full text-[11.5px] leading-relaxed text-slate-400">
        {ownKeysHelp}
      </p>
    </div>
  );
}

/**
 * One limit row: the figure, a bar when there is a ceiling to draw against, the
 * ceiling in words, what it counts and how it moves.
 *
 * `percent` is the server's, not a recomputation — the same number the service
 * used to decide `exceeded`, so the bar and the banner cannot disagree. The bar
 * width is clamped to full while the label is not: being at 143% of a cap is
 * worth reading, and a bar that stops at full is what a bar is for.
 */
function LimitRow({ item, exceeded }: { item: LimitItem; exceeded: boolean }) {
  const uncapped = item.limit === null || item.limit === undefined;
  const showBar = !item.lifted && !uncapped && item.percent !== null;
  const percent = item.percent ?? 0;

  const value = item.lifted
    ? `${formatUsed(item, item.used)}${unitSuffix(item)} · not capped`
    : uncapped
      ? `${formatUsed(item, item.used)}${unitSuffix(item)} · no limit`
      : `${formatUsed(item, item.used)} of ${formatUsed(item, item.limit as number)}${unitSuffix(item)}`;

  return (
    <div className="border-b border-slate-100 py-3.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="min-w-40 flex-1 text-sm font-bold text-slate-900">
          {item.label}
        </span>
        {exceeded && (
          <Chip tone={item.enforced ? "rose" : "amber"} size="sm">
            <Icon name="warn" className="size-3" />
            {item.enforced ? "Blocking" : "No headroom"}
          </Chip>
        )}
        <span className="font-mono text-[12.5px] font-bold whitespace-nowrap text-slate-600">
          {value}
        </span>
      </div>

      {showBar && (
        <div
          className="my-2 h-[7px] overflow-hidden rounded-full border border-slate-100 bg-slate-50"
          role="img"
          aria-label={`${value} used, ${Math.round(percent)}%`}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-500",
              percent >= 90
                ? "bg-rose-500"
                : percent >= 70
                  ? "bg-amber-500"
                  : "bg-blue-600",
            )}
            style={{ width: `${Math.min(100, Math.max(percent, 0))}%` }}
          />
        </div>
      )}

      <p className="mt-1 text-[11.5px] font-semibold text-slate-600">
        Maximum: {item.maximum}
        {item.lifted ? " — not applied to you." : "."}
      </p>
      <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-400">
        {item.note}
      </p>
      <EscapeRoute item={item} />
    </div>
  );
}

function OwnCredentialsChip({ providers }: { providers: string[] }) {
  if (!providers.length) {
    return (
      <Chip tone="amber" size="sm">
        <Icon name="cloud" className="size-3" />
        Running entirely on FutureSmart platform keys
      </Chip>
    );
  }
  return (
    <Chip tone="green" size="sm">
      <Icon name="key" className="size-3" />
      Using your own keys for {joinList(providers.map(providerLabel))}
    </Chip>
  );
}

export default function PlanLimits() {
  const limits = useOwnerLimits();

  if (limits.isLoading) {
    return (
      <Card>
        <CardHeader
          title="Your plan"
          note="what this workspace is allowed to use"
        />
        <CardBody>
          <RowsSkeleton rows={5} />
        </CardBody>
      </Card>
    );
  }

  if (limits.error) {
    return (
      <Card>
        <CardHeader title="Your plan" />
        <CardBody className="text-sm text-rose-600">
          {apiMessage(limits.error)}
        </CardBody>
      </Card>
    );
  }

  if (!limits.data) {
    return (
      <Card>
        <CardHeader title="Your plan" />
        <CardBody className="text-sm text-slate-400">
          No limits reported for this workspace.
        </CardBody>
      </Card>
    );
  }

  const data = limits.data;
  const exceeded = new Set(data.exceeded ?? []);
  const window = data.billing_window;
  const windowLabel = `${dayjs(window.start).format("D MMM YYYY")} – ${dayjs(window.end).format("D MMM YYYY")}`;

  /**
   * Only an enforced, exceeded limit gets the outage banner. A row at 100% that
   * changes nothing must not look like a row at 100% that stops answers, so the
   * banner is gated on `enforced`, not on membership of `exceeded`.
   */
  const blocking = data.groups
    .flatMap((group) => group.items)
    .filter((item) => item.enforced && exceeded.has(item.key));

  return (
    <div>
      <Card className="mb-4">
        <CardHeader
          title="Your plan"
          note="what this workspace is allowed to use"
        />
        <CardBody className="grid gap-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="blue" size="sm">
              <Icon name="bolt" className="size-3" />
              {data.tier.name} tier
            </Chip>
            <OwnCredentialsChip providers={data.own_credentials ?? []} />
          </div>
          <p className="max-w-[80ch] text-sm text-slate-600">
            Every limit below is counted across every database agent in this
            workspace, and is priced at ${data.token_rate_usd} per token where a
            figure is a cost.
          </p>
          <p className="max-w-[80ch] text-[11.5px] leading-relaxed text-slate-400">
            Billing period · {windowLabel} ({window.days} days).{" "}
            <b>The consumption-source filter does not apply on this tab</b> — a
            limit is enforced against every request the platform served,
            whichever key paid for it — and neither does the period selector,
            because a ceiling anchored to a window the reader can change is
            meaningless.
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            <Link
              href={ROUTES.credentials}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              Add your credentials
            </Link>
          </div>
        </CardBody>
      </Card>

      {blocking.map((item) => (
        <Banner
          key={item.key}
          tone="error"
          title={`${item.label} reached`}
          className="mb-4"
        >
          New requests are being refused for this workspace until this allowance
          frees up. {item.maximum}.
        </Banner>
      ))}

      {data.groups.map((group) => (
        <div key={group.group}>
          <p className="mt-4.5 mb-2 text-[10px] font-bold tracking-[0.07em] text-slate-400 uppercase">
            {group.group}
          </p>
          <Card>
            <CardBody>
              {group.items.map((item) => (
                <LimitRow
                  key={item.key}
                  item={item}
                  exceeded={exceeded.has(item.key)}
                />
              ))}
            </CardBody>
          </Card>
        </div>
      ))}
    </div>
  );
}
