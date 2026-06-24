import { Button, FieldError, Input, Label } from "@/components/ui";
import { ROLE_LABELS } from "@/constants";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

type InvitePreview = { company_name: string | null; email: string; role: string };

export default function AcceptInvitePage() {
  const { user, acceptInvite, loading: authLoading } = useAuth();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(true);

  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setLoadError("Davet bağlantısı geçersiz.");
      setLoadingPreview(false);
      return;
    }
    let alive = true;
    (async () => {
      try {
        const { data } = await apiGet<InvitePreview>(`/auth/invite/${token}`);
        if (alive) setPreview(data);
      } catch (e: any) {
        if (alive) setLoadError(e.message ?? "Davet bulunamadı veya süresi dolmuş.");
      } finally {
        if (alive) setLoadingPreview(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  // An already-signed-in user is bound to their own company; sending them here
  // would only hit the "zaten bir şirkete kayıtlısınız" guard. Bounce to the app.
  if (!authLoading && user) return <Navigate to="/dashboard" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!preview) return;
    setSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      await acceptInvite(token, preview.email, password, fullName, mode);
      toast.success("Davet kabul edildi");
      navigate("/dashboard");
    } catch (err: any) {
      // signUp with email confirmation returns an informational message, not an
      // error — surface it and nudge the user toward the sign-in branch.
      if (mode === "signup" && /onaylay/i.test(err.message ?? "")) {
        setInfo(err.message);
        setMode("signin");
      } else {
        setError(err.message ?? "İşlem başarısız");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-primary p-4">
      <div className="w-full max-w-sm rounded-xl bg-surface p-8 shadow-lg">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-xl font-bold text-white">Y</div>
          <div>
            <h1 className="text-xl font-bold text-primary">Yapı</h1>
            <p className="text-xs text-text-secondary">İnşaat Proje Yönetimi</p>
          </div>
        </div>

        {loadingPreview ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : loadError ? (
          <div className="space-y-4">
            <FieldError message={loadError} />
            <p className="text-sm text-text-secondary">
              Davetin süresi dolmuş veya iptal edilmiş olabilir. Lütfen sizi davet eden kişiden yeni bir bağlantı isteyin.
            </p>
            <Button type="button" variant="ghost" className="w-full" onClick={() => navigate("/login")}>
              Giriş sayfasına dön
            </Button>
          </div>
        ) : preview ? (
          <>
            <p className="mb-4 text-sm text-text-secondary">
              <span className="font-semibold text-primary">{preview.company_name ?? "Bir şirket"}</span> sizi{" "}
              <span className="font-semibold text-primary">{ROLE_LABELS[preview.role] ?? preview.role}</span> olarak ekibe davet etti.
            </p>

            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <Label htmlFor="email">E-posta</Label>
                <Input id="email" type="email" value={preview.email} readOnly disabled />
              </div>
              <div>
                <Label required htmlFor="fullname">Ad Soyad</Label>
                <Input id="fullname" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </div>
              <div>
                <Label required htmlFor="password">Şifre</Label>
                <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              {error && <FieldError message={error} />}
              {info && <p className="rounded bg-navy-50 p-2 text-xs text-primary-light">{info}</p>}
              <Button type="submit" className="w-full" loading={submitting}>
                {mode === "signup" ? "Hesap Oluştur ve Katıl" : "Giriş Yap ve Katıl"}
              </Button>
            </form>

            <p className="mt-4 text-center text-xs text-text-secondary">
              {mode === "signup" ? "Zaten bir hesabınız var mı? " : "Yeni hesap mı oluşturacaksınız? "}
              <button
                type="button"
                className="font-medium text-primary hover:underline"
                onClick={() => {
                  setMode(mode === "signup" ? "signin" : "signup");
                  setError(null);
                  setInfo(null);
                }}
              >
                {mode === "signup" ? "Giriş yaparak katılın" : "Hesap oluşturun"}
              </button>
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
