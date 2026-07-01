// CR-044 — trigger a browser download of a (short-lived, signed) file URL. The
// URL already carries its own auth (a signed Supabase Storage URL), so no header
// is needed — a plain anchor click works. We set `download` so the saved file
// keeps its friendly name; some browsers ignore it for cross-origin signed URLs,
// in which case the file still downloads via its Content-Disposition header.
export function downloadFromUrl(url: string, fileName?: string) {
  const a = document.createElement("a");
  a.href = url;
  if (fileName) a.download = fileName;
  a.rel = "noopener";
  a.target = "_blank";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
