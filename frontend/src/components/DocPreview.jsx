import { getPreviewUrl, getDownloadUrl } from '../api'

export default function DocPreview({ jobId }) {
  if (!jobId) return null

  const previewUrl  = getPreviewUrl(jobId)
  const downloadUrl = getDownloadUrl(jobId)

  return (
    <div className="result-area">
      <div className="result-top">
        <span className="result-title">📄 Синопсис протокола</span>
        <a
          href={downloadUrl}
          className="btn-download"
          download
          target="_blank"
          rel="noreferrer"
        >
          ⬇ Скачать .docx
        </a>
      </div>

      <iframe
        className="preview-frame"
        src={previewUrl}
        title="Предпросмотр синопсиса"
      />
    </div>
  )
}
