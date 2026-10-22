"use client";

import Icon from "@/components/Icon";
import Modal from "@/components/ui/Modal";
import { Button } from "@/platform/components/ui";

import { ADD_DB_MODES, type AddDbMode } from "./constants";

/**
 * Chooser for "Add database": one purpose-built flow per mode rather than a
 * single form with three shapes stuffed into it. Each mode opens its own modal,
 * so the RDS path can be the two-step flow it needs to be and the import path
 * can carry a file drop, without either complicating the common case.
 */
export default function AddDatabaseMenuModal({
  onPick,
  onClose,
}: {
  onPick: (mode: AddDbMode) => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title="Add a database"
      sub="Three ways in — pick the one that matches what you have."
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
    >
      <div
        role="menu"
        aria-label="How to add the database"
        className="space-y-3"
      >
        {ADD_DB_MODES.map(([mode, title, hint, glyph]) => (
          <button
            key={mode}
            type="button"
            role="menuitem"
            onClick={() => onPick(mode)}
            className="w-full cursor-pointer rounded-lg border border-slate-200 bg-white p-4 text-left transition-colors hover:border-indigo-400 hover:bg-indigo-50/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40"
          >
            <Icon name={glyph} className="size-5 text-indigo-600" />
            <span className="mt-2 block text-sm font-semibold text-slate-900">
              {title}
            </span>
            <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
