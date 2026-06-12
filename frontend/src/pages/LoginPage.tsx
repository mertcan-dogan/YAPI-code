import { Button, FieldError, Input, Label } from "@/components/ui";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

export default function LoginPage() {
  const { user, login, register, loading } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (!loading && user) return <Navigate to="/dashboard" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      if (mode === "login") {
        await login(email, password);
        toast.success("Giriş başarılı");
        navigate("/dashboard");
      } else {
        await register(email, password, companyName, fullName);
        toast.success("Kayıt başarılı");
        navigate("/dashboard");
      }
    } catch (err: any) {
      // signUp without auto-session returns an informational message, not an error.
      if (mode === "register" && /onaylay/i.test(err.message ?? "")) {
        setInfo(err.message);
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

        <form onSubmit={onSubmit} className="space-y-4">
          {mode === "register" && (
            <>
              <div>
                <Label required htmlFor="company">Şirket Adı</Label>
                <Input id="company" value={companyName} onChange={(e) => setCompanyName(e.target.value)} required placeholder="Test Şirketi" />
              </div>
              <div>
                <Label required htmlFor="fullname">Ad Soyad</Label>
                <Input id="fullname" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </div>
            </>
          )}
          <div>
            <Label required htmlFor="email">E-posta</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="ornek@sirket.com" />
          </div>
          <div>
            <Label required htmlFor="password">Şifre</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <FieldError message={error} />}
          {info && <p className="rounded bg-navy-50 p-2 text-xs text-primary-light">{info}</p>}
          <Button type="submit" className="w-full" loading={submitting}>
            {mode === "login" ? "Giriş Yap" : "Kayıt Ol"}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-text-secondary">
          {mode === "login" ? "Hesabınız yok mu? " : "Zaten hesabınız var mı? "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
              setInfo(null);
            }}
          >
            {mode === "login" ? "Yeni şirket kaydı oluşturun" : "Giriş yapın"}
          </button>
        </p>
      </div>
    </div>
  );
}
