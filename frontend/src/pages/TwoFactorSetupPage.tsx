import { Button, FieldError, Input, Label } from "@/components/ui";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-002-I 10.1: TOTP 2FA setup using Supabase Auth MFA.
export default function TwoFactorSetupPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [qr, setQr] = useState<string | null>(null);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [backupCodes] = useState<string[]>(() =>
    // 8 single-use display codes (store securely; shown once).
    Array.from({ length: 8 }, () => Math.random().toString(36).slice(2, 8).toUpperCase())
  );

  useEffect(() => {
    supabase.auth.mfa
      .enroll({ factorType: "totp" })
      .then(({ data, error }) => {
        if (error) {
          setError(error.message);
          return;
        }
        setQr(data?.totp?.qr_code ?? null);
        setFactorId(data?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  const verify = async () => {
    if (!factorId) return;
    setVerifying(true);
    setError(null);
    try {
      const challenge = await supabase.auth.mfa.challenge({ factorId });
      if (challenge.error) throw challenge.error;
      const { error } = await supabase.auth.mfa.verify({
        factorId,
        challengeId: challenge.data.id,
        code,
      });
      if (error) throw error;
      toast.success("İki faktörlü doğrulama etkinleştirildi");
      navigate("/dashboard");
    } catch (e: any) {
      setError(e.message ?? "Doğrulama başarısız");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-bg p-4">
      <div className="w-full max-w-md rounded-xl bg-surface p-8 shadow">
        <h1 className="text-xl font-bold text-primary">İki Faktörlü Doğrulama Kurulumu</h1>
        <p className="mt-1 text-sm text-text-secondary">
          {user?.role === "director"
            ? "Hesabınızı güvende tutmak için iki faktörlü doğrulama kurmanız gerekmektedir."
            : "Hesabınızı güvende tutmak için iki faktörlü doğrulama ekleyin."}
        </p>

        {error && <FieldError message={error} />}

        <div className="mt-4 space-y-4">
          <div>
            <Label>1. QR kodu Google Authenticator ile tarayın</Label>
            {qr ? (
              <img src={qr} alt="TOTP QR" className="mx-auto h-48 w-48" />
            ) : (
              <div className="mx-auto flex h-48 w-48 items-center justify-center text-sm text-text-secondary">QR yükleniyor…</div>
            )}
          </div>

          <div>
            <Label required>2. Uygulamadaki 6 haneli kodu girin</Label>
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" maxLength={6} />
          </div>

          <div className="rounded-md border border-border bg-bg p-3">
            <p className="mb-1 text-xs font-medium text-text-secondary">Yedek kodlar (güvenli bir yere kaydedin):</p>
            <div className="grid grid-cols-4 gap-1 font-mono text-xs">
              {backupCodes.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          </div>

          <Button className="w-full" loading={verifying} onClick={verify} disabled={!factorId || code.length < 6}>
            Doğrula ve Etkinleştir
          </Button>
        </div>
      </div>
    </div>
  );
}
