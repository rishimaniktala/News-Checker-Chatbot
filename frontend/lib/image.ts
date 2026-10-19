export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg"];

export function imageProblem(file: { type: string; size: number }): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "Use a PNG or JPG image.";
  if (file.size > MAX_IMAGE_BYTES) return "The image is over 5 MB.";
  return null;
}

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(new Error("Could not read the image."));
    r.readAsDataURL(file);
  });
}
