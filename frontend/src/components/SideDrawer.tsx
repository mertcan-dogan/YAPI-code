import { cn } from "@/lib/cn";
import { X } from "lucide-react";
import * as React from "react";
import { Button } from "./ui";

// Side Drawer — Section 6.5 (480px desktop, full width mobile, slide-in)
interface SideDrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  onSave?: () => void;
  saving?: boolean;
  dirty?: boolean;
  children: React.ReactNode;
  saveLabel?: string;
}

export function SideDrawer({ open, title, onClose, onSave, saving, dirty, children, saveLabel = "Kaydet" }: SideDrawerProps) {
  if (!open) return null;

  const handleClose = () => {
    if (dirty && !window.confirm("Kaydedilmemiş değişiklikler var. Kapatmak istediğinize emin misiniz?")) return;
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={handleClose} />
      <div className="absolute right-0 top-0 flex h-full w-full max-w-[480px] flex-col bg-surface shadow-xl animate-slide-in">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold text-primary">{title}</h3>
          <button onClick={handleClose} className="text-text-secondary hover:text-text-primary">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {onSave && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
            <Button variant="ghost" onClick={handleClose}>
              İptal
            </Button>
            <Button onClick={onSave} loading={saving}>
              {saveLabel}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
