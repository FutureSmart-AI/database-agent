import AppShell from "@/components/shell/AppShell";
import UsageView from "@/components/usage/UsageView";

/**
 * `flush` because this screen owns its own canvas: it paints the slate
 * background edge to edge and supplies its own padding. It also gives the view
 * a parent with a definite height, which is what `min-h-full` inside it needs
 * to resolve against — under the shell's default auto-height padding wrapper it
 * resolved against nothing, and a short tab left a white band below the panel.
 */
export default function UsagePage() {
  return (
    <AppShell title="Usage & Limits" flush>
      <UsageView />
    </AppShell>
  );
}
