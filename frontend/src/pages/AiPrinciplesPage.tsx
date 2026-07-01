import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { PageHeader } from "@/components/layout/AppLayout";
import { EyeOff, FileText, Lock, ShieldCheck, Sparkles, UserCheck } from "lucide-react";

// CR-024-C — static "Yapı AI — İlkeler & Güvenlik" page. Each line is literally
// true of the system today (§0.2.3): NO SOC/GAAP/ISO/EU-AI-Act claims — we win on
// honesty, not borrowed badges.
const PRINCIPLES = [
  {
    icon: Lock,
    title: "Salt-okunur",
    body: "Yapı AI verilerinizi yalnızca okur; onayınız olmadan hiçbir kayıt oluşturmaz veya değiştirmez.",
  },
  {
    icon: ShieldCheck,
    title: "Verileriniz size özel",
    body: "Her sorgu yalnızca kendi şirketinizin verisinde çalışır (satır-düzeyi güvenlik / RLS izolasyonu).",
  },
  {
    icon: FileText,
    title: "Her yanıt kaynak gösterir",
    body: "Yanıtlar, dayandığı kayıtlara bağlantı (atıf) içerir.",
  },
  {
    icon: EyeOff,
    title: "Gizlilik",
    body: "Hata izleme sistemine kişisel veya finansal veri gönderilmez.",
  },
  {
    icon: UserCheck,
    title: "İnsan kontrolü",
    body: "AI yardımcıdır; kararlar ve onaylar size aittir.",
  },
];

export default function AiPrinciplesPage() {
  return (
    <div>
      <PageHeader
        title="Yapı AI — İlkeler & Güvenlik"
        subtitle="Yapı AI'nın nasıl çalıştığı ve verilerinizi nasıl koruduğu."
      />
      <div className="mx-auto max-w-2xl space-y-3">
        {PRINCIPLES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="flex gap-3 rounded-xl border border-border bg-surface p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-navy-50 text-brand">
              <Icon className="h-5 w-5" />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-primary">{title}</h3>
              <p className="mt-0.5 text-sm text-text-secondary">{body}</p>
            </div>
          </div>
        ))}

        <p className="flex items-center gap-2 rounded-xl border border-dashed border-border bg-bg p-4 text-sm text-text-secondary">
          <Sparkles className="h-4 w-4 shrink-0 text-brand" />
          Yapı AI gelişmeye devam ediyor; geri bildirimleriniz onu iyileştirir.
        </p>

        <div className="pt-1">
          <AiTrustBadge />
        </div>
      </div>
    </div>
  );
}
