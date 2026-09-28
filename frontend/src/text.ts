/** Lowercase, accent-free form for search: "İstanbul", "ISTANBUL" and "istanbul" all match. */
export function searchKey(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // combining accents (also the dot of Turkish İ)
    .replace(/ı/g, "i") // Turkish dotless i
    .toLowerCase();
}
