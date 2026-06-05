import { Button, FieldError, Input, Label } from "@/components/ui";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

export default function LoginPage() {
  const { user, login, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!loading && user) return <Navigate to="/dashboard" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      toast.success("Giriş başarılı");
      navigate("/dashboard");
    } catch (err: any) {
      setError(err.message ?? "Giriş başarısız");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-primary p-4">
      <div className="w-full max-w-sm rounded-xl bg-surface p-8 shadow-lg">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded bg-accent text-xl font-bold text-primary">Y</div>
          <div>
            <h1 className="text-xl font-bold text-primary">Yapı</h1>
            <p className="text-xs text-text-secondary">İnşaat Proje Yönetimi</p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <Label required htmlFor="email">E-posta</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="ornek@sirket.com" />
          </div>
          <div>
            <Label required htmlFor="password">Şifre</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <FieldError message={error} />}
          <Button type="submit" className="w-full" loading={submitting}>
            Giriş Yap
          </Button>
        </form>
      </div>
    </div>
  );
}
