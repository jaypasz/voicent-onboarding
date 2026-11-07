// Mirrors the backend's allow-list (backend/app/steps/upload.py). SVG is deliberately absent: it can carry script.
export const UPLOAD_TYPES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', pdf: 'application/pdf',
  mp4: 'video/mp4', mov: 'video/quicktime', csv: 'text/csv', txt: 'text/plain',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

export function extensionOf(name: string): string {
  return name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
}

/** Why a chosen file can't be used, in plain words, or null if it's fine. The server checks again. */
export function fileProblem(file: { name: string; size: number }, accept: string[], maxMb: number): string | null {
  const ext = extensionOf(file.name)
  if (!accept.includes(ext)) return `${file.name}: this type of file isn't allowed here. Use ${accept.join(', ')}.`
  if (file.size <= 0) return `${file.name}: the file is empty.`
  if (file.size > maxMb * 1024 * 1024) return `${file.name}: files can be up to ${maxMb} MB.`
  return null
}

/** PUT a file to the signed storage URL, reporting progress. Mirrors Supabase's uploadToSignedUrl (multipart PUT). */
export function putToSignedUrl(url: string, file: File, onProgress: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (status ${xhr.status}).`)))
    xhr.onerror = () => reject(new Error("The upload didn't go through. Check your connection and try again."))
    const body = new FormData()
    body.append('cacheControl', '3600')
    body.append('', file)
    xhr.send(body)
  })
}
