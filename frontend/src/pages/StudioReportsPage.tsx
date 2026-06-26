import { PageHeader } from "@/components/layout/AppLayout";
import { DataTable, type Column } from "@/components/DataTable";
import { Avatar, Badge, Button, Menu, MenuItem, Tabs } from "@/components/ui";
import { studio } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { ReportListItem } from "@/types/studio";
import { formatDateTime } from "@/utils/format";
import {
  AreaChart,
  BarChart3,
  Copy,
  Hash,
  LineChart,
  Lock,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Table as TableIcon,
  Trash2,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

// Small icon by the report's saved viz (spec.viz, carried on the list item).
function VizIcon({ viz }: { viz: string }) {
  const Icon =
    viz === "bar" ? BarChart3 : viz === "area" ? AreaChart : viz === "kpi" ? Hash : viz === "table" ? TableIcon : LineChart;
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-blue-soft text-brand">
      <Icon className="h-4 w-4" />
    </span>
  );
}

function VisibilityChip({ visibility }: { visibility: string }) {
  if (visibility === "company") {
    return (
      <Badge variant="success">
        <Users className="h-3 w-3" /> Herkes
      </Badge>
    );
  }
  return (
    <Badge variant="neutral">
      <Lock className="h-3 w-3" /> Özel
    </Badge>
  );
}

export default function StudioReportsPage() {
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState<"mine" | "all">("mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounce the search box → the server-side ?q= filter.
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(() => {
    setLoading(true);
    studio
      .listReports(q || undefined)
      .then((data) => {
        setItems(data ?? []);
        setError(null);
      })
      .catch((e) => setError(e?.message ?? "Raporlar yüklenemedi."))
      .finally(() => setLoading(false));
  }, [q]);

  useEffect(() => {
    load();
  }, [load]);

  const canEdit = useCallback(
    (row: ReportListItem) => user?.role === "director" || row.owner_id === user?.id,
    [user]
  );

  const rows = useMemo(
    () => (tab === "mine" ? items.filter((r) => r.owner_id === user?.id) : items),
    [items, tab, user]
  );

  const onDuplicate = async (row: ReportListItem) => {
    try {
      const created = await studio.duplicateReport(row.id);
      toast.success("Rapor çoğaltıldı");
      navigate(`/studio/reports/${created.id}`);
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor çoğaltılamadı");
    }
  };

  const onDelete = async (row: ReportListItem) => {
    if (!window.confirm(`"${row.title}" raporunu silmek istediğinize emin misiniz?`)) return;
    try {
      await studio.deleteReport(row.id);
      toast.success("Rapor silindi");
      load();
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor silinemedi");
    }
  };

  const columns: Column<ReportListItem>[] = [
    {
      key: "title",
      header: "Ad",
      render: (row) => (
        <div className="flex items-center gap-3">
          <VizIcon viz={row.viz} />
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold text-text-primary">{row.title}</div>
            {row.labels && row.labels.length > 0 && (
              <div className="mt-0.5 flex flex-wrap gap-1">
                {row.labels.map((l) => (
                  <span key={l} className="rounded-sm bg-surface-hover px-1.5 py-px text-[10px] text-text-muted">
                    {l}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "owner",
      header: "Sahip",
      render: (row) => {
        const mine = row.owner_id === user?.id;
        return (
          <div className="flex items-center gap-2 text-[13px] text-text-secondary">
            <Avatar name={mine ? user?.full_name : "Kullanıcı"} size={22} />
            <span>{mine ? "Siz" : "Başka kullanıcı"}</span>
          </div>
        );
      },
    },
    {
      key: "visibility",
      header: "Görünürlük",
      render: (row) => <VisibilityChip visibility={row.visibility} />,
    },
    {
      key: "updated_at",
      header: "Güncellenme",
      render: (row) => <span className="text-[13px] text-text-muted">{formatDateTime(row.updated_at)}</span>,
      sortValue: (row) => row.updated_at,
      sortable: true,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (row) => (
        // Stop row-click navigation from firing when interacting with the menu.
        <div onClick={(e) => e.stopPropagation()}>
          <Menu
            align="right"
            triggerLabel={`Rapor işlemleri: ${row.title}`}
            trigger={<MoreHorizontal className="h-[18px] w-[18px] text-text-muted" />}
          >
            {(close) => (
              <>
                {canEdit(row) && (
                  <MenuItem
                    icon={Pencil}
                    onClick={() => {
                      close();
                      navigate(`/studio/reports/${row.id}`);
                    }}
                  >
                    Düzenle
                  </MenuItem>
                )}
                <MenuItem
                  icon={Copy}
                  onClick={() => {
                    close();
                    onDuplicate(row);
                  }}
                >
                  Çoğalt
                </MenuItem>
                {canEdit(row) && (
                  <MenuItem
                    icon={Trash2}
                    danger
                    onClick={() => {
                      close();
                      onDelete(row);
                    }}
                  >
                    Sil
                  </MenuItem>
                )}
              </>
            )}
          </Menu>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Rapor Stüdyosu"
        subtitle="Kayıtlı raporlarınızı görüntüleyin, düzenleyin ve yeni rapor oluşturun."
        breadcrumb="Stüdyo"
        action={
          <Button onClick={() => navigate("/studio/reports/new")}>
            <Plus className="h-4 w-4" /> Rapor ekle
          </Button>
        }
      />

      {/* AI hero — CR-035 not wired; routes to the blank editor, no agent call. */}
      <button
        type="button"
        onClick={() => navigate("/studio/reports/new")}
        className="mb-5 flex w-full items-center gap-3 rounded-card border border-blue-border bg-gradient-to-r from-blue-soft to-purple-soft px-4 py-3 text-left transition-colors hover:brightness-[0.98]"
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-control bg-white text-purple">
          <Sparkles className="h-5 w-5" />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-text-primary">Yapay zekâ ile oluştur</span>
          <span className="block text-xs text-text-secondary">
            Ne görmek istediğinizi yazın — Yapı AI raporu sizin için kursun (yakında).
          </span>
        </span>
      </button>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          tabs={[
            { id: "mine", label: "Raporlarım" },
            { id: "all", label: "Tüm raporlar" },
          ]}
          value={tab}
          onChange={(id) => setTab(id as "mine" | "all")}
        />
        <div className="flex-1" />
        <div className="flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm text-text-secondary">
          <Search className="h-4 w-4 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rapor ara…"
            aria-label="Rapor ara"
            className="w-40 bg-transparent outline-none placeholder:text-text-faint"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={error}
        onRetry={load}
        onRowClick={(row) => navigate(`/studio/reports/${row.id}`)}
        emptyMessage={
          tab === "mine" ? "Henüz rapor oluşturmadınız." : "Görüntülenecek rapor yok."
        }
        emptyAction={{ label: "Rapor ekle", onClick: () => navigate("/studio/reports/new") }}
      />
    </div>
  );
}
