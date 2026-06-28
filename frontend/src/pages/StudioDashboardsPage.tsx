// CR-034 — Panolar (dashboards) list. Mirrors StudioReportsPage: tabs
// Panolarım / Tüm panolar, debounced server-side search, a table with a pano icon
// + widget-count badge, owner, visibility chip and last-updated, and a row "…"
// menu (Çoğalt / Bağlantıyı kopyala / Sil). Sil is gated to the owner or a
// director (canEdit); Çoğalt is available for any viewable pano. Loading / empty /
// error states are handled by DataTable (a failed fetch never reads as empty).
import { PageHeader } from "@/components/layout/AppLayout";
import { DataTable, type Column } from "@/components/DataTable";
import { Avatar, Badge, MenuItem, RowMenu, Tabs, Button } from "@/components/ui";
import { studio } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { DashboardListItem } from "@/types/studio";
import { formatDateTime } from "@/utils/format";
import { Copy, LayoutDashboard, Link2, Lock, MoreHorizontal, Plus, Search, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

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

export default function StudioDashboardsPage() {
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState<"mine" | "all">("mine");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<DashboardListItem[]>([]);
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
      .listDashboards(q || undefined)
      .then((data) => {
        setItems(data ?? []);
        setError(null);
      })
      .catch((e) => setError(e?.message ?? "Panolar yüklenemedi."))
      .finally(() => setLoading(false));
  }, [q]);

  useEffect(() => {
    load();
  }, [load]);

  const canEdit = useCallback(
    (row: DashboardListItem) => user?.role === "director" || row.owner_id === user?.id,
    [user]
  );

  const rows = useMemo(
    () => (tab === "mine" ? items.filter((d) => d.owner_id === user?.id) : items),
    [items, tab, user]
  );

  const onDuplicate = async (row: DashboardListItem) => {
    try {
      const created = await studio.duplicateDashboard(row.id);
      toast.success("Pano çoğaltıldı");
      navigate(`/studio/dashboards/${created.id}`);
    } catch (e: any) {
      toast.error(e?.message ?? "Pano çoğaltılamadı");
    }
  };

  const onCopyLink = async (row: DashboardListItem) => {
    const url = `${window.location.origin}/studio/dashboards/${row.id}`;
    try {
      await navigator.clipboard?.writeText(url);
      toast.success("Bağlantı kopyalandı");
    } catch {
      // Clipboard API unavailable (or denied) — surface the link so the user can copy it.
      window.prompt("Bağlantıyı kopyalayın", url);
    }
  };

  const onDelete = async (row: DashboardListItem) => {
    if (!window.confirm(`"${row.title}" panosunu silmek istediğinize emin misiniz?`)) return;
    try {
      await studio.deleteDashboard(row.id);
      toast.success("Pano silindi");
      load();
    } catch (e: any) {
      toast.error(e?.message ?? "Pano silinemedi");
    }
  };

  const columns: Column<DashboardListItem>[] = [
    {
      key: "title",
      header: "Ad",
      render: (row) => (
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-teal-soft text-teal">
            <LayoutDashboard className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13px] font-semibold text-text-primary">{row.title}</span>
              <Badge variant="neutral">
                {row.widget_count} widget
              </Badge>
            </div>
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
          <RowMenu
            align="right"
            triggerLabel={`Pano işlemleri: ${row.title}`}
            trigger={<MoreHorizontal className="h-[18px] w-[18px] text-text-muted" />}
          >
            {(close) => (
              <>
                <MenuItem
                  icon={Copy}
                  onClick={() => {
                    close();
                    onDuplicate(row);
                  }}
                >
                  Çoğalt
                </MenuItem>
                <MenuItem
                  icon={Link2}
                  onClick={() => {
                    close();
                    onCopyLink(row);
                  }}
                >
                  Bağlantıyı kopyala
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
          </RowMenu>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Panolar"
        subtitle="Kayıtlı panolarınızı görüntüleyin, düzenleyin ve yeni pano oluşturun."
        breadcrumb="Stüdyo"
        action={
          <Button onClick={() => navigate("/studio/dashboards/new")}>
            <Plus className="h-4 w-4" /> Pano ekle
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          tabs={[
            { id: "mine", label: "Panolarım" },
            { id: "all", label: "Tüm panolar" },
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
            placeholder="Pano ara…"
            aria-label="Pano ara"
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
        onRowClick={(row) => navigate(`/studio/dashboards/${row.id}`)}
        emptyMessage={tab === "mine" ? "Henüz pano oluşturmadınız." : "Görüntülenecek pano yok."}
        emptyAction={{ label: "Pano ekle", onClick: () => navigate("/studio/dashboards/new") }}
      />
    </div>
  );
}
