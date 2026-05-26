export function downloadBlob(response, fallbackName = 'download') {
    const blob = response?.data instanceof Blob ? response.data : new Blob([response?.data || '']);
    const disposition = response?.headers?.['content-disposition'] || '';
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    const filename = decodeURIComponent(match?.[1] || match?.[2] || fallbackName);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}
