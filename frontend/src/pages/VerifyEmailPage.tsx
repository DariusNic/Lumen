import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/layout/Logo";
import * as authApi from "@/api/auth.api";
import { parseApiError } from "@/api/client";

/**
 * Landing page for the email link in the verification message. Auto-fires
 * the POST /api/auth/verify-email call on mount, then routes the user to
 * /auth?mode=login on success (the email client may not be the same
 * browser session as the one they registered in).
 */
export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");
  const [errorMessage, setErrorMessage] = useState<string>("");
  // React StrictMode double-invokes effects in dev. Guard with a ref so the
  // one-shot token isn't burned on the first dry-run.
  const consumed = useRef(false);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMessage("This verification link is missing its token.");
      return;
    }
    if (consumed.current) return;
    consumed.current = true;
    authApi
      .verifyEmail(token)
      .then(() => setStatus("success"))
      .catch((err) => {
        setStatus("error");
        setErrorMessage(parseApiError(err));
      });
  }, [token]);

  return (
    <div className="flex min-h-screen flex-col bg-background p-md">
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="mb-lg text-center animate-blur-up">
          <Link to="/" className="focus-ring inline-block rounded-lg" aria-label="Lumen home">
            <Logo size="lg" />
          </Link>
        </div>

        <div className="w-full max-w-[440px] rounded-xl border border-border bg-surface p-xl shadow-card animate-slide-up text-center">
          {status === "pending" && (
            <>
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-primary-tint text-primary">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Verifying your email…</h1>
              <p className="mt-2 text-body text-text-muted">
                One moment while we activate your account.
              </p>
            </>
          )}

          {status === "success" && (
            <>
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-success/15 text-success">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Email verified</h1>
              <p className="mt-2 text-body text-text-muted">
                Your account is active. Log in to start using Lumen.
              </p>
              <Button asChild variant="primary" size="lg" className="mt-lg w-full">
                <Link to="/auth?mode=login">Continue to log in</Link>
              </Button>
            </>
          )}

          {status === "error" && (
            <>
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-warning/15 text-warning-700">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">We couldn't verify this link</h1>
              <p className="mt-2 text-body text-text-muted">{errorMessage}</p>
              <div className="mt-lg flex flex-col gap-2">
                <Button asChild variant="primary">
                  <Link to="/auth?mode=login">
                    <Mail className="h-4 w-4" /> Go to log in
                  </Link>
                </Button>
                <p className="text-body-small text-text-muted">
                  From the login screen you can request a fresh verification email.
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      <footer className="mt-lg text-center text-uppercase-label uppercase text-text-muted">
        © 2026 Lumen
      </footer>
    </div>
  );
}
