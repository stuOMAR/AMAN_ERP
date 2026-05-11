import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUpDown, Download, Search } from 'lucide-react';
import Pagination, { usePagination } from './Pagination';
import EmptyState from './EmptyState';
import { PageLoading } from './LoadingStates';

/**
 * Shared DataTable component — replaces duplicated table markup across list pages.
 *
 * Props:
 *   columns     — [{ key, label, width?, render?, style?, headerStyle? }]
 *   data        — array of row objects
 *   loading     — show loading spinner
 *   emptyIcon   — icon for empty state
 *   emptyTitle  — heading when no data
 *   emptyDesc   — description when no data
 *   emptyAction — { label, onClick } for CTA button in empty state
 *   onRowClick  — (row) => void
 *   rowKey      — field name for React key (default "id")
 *   paginate    — enable built-in pagination (default true)
 *   pageSize    — initial page size (default 25)
 *   searchValue — controlled search value (optional)
 *   onSearch    — (value) => void (optional)
 *   searchable  — enable built-in search across visible column values
 *   sortable    — enable client-side sorting by column
 *   exportable  — show CSV export action
 *   sticky       — column option: "start" or "end" for horizontally pinned columns
 */
export default function DataTable({
    columns = [],
    data = [],
    loading = false,
    emptyIcon = '📋',
    emptyTitle,
    emptyDesc,
    emptyAction,
    onRowClick,
    rowKey = 'id',
    paginate = true,
    pageSize: initialPageSize = 25,
    searchValue,
    onSearch,
    searchPlaceholder,
    searchable = false,
    sortable = true,
    exportable = false,
    exportName = 'table-export',
    stickyActions = false,
}) {
    const { t } = useTranslation();
    const [internalSearch, setInternalSearch] = useState('');
    const [sortConfig, setSortConfig] = useState(null);
    const currentSearch = onSearch !== undefined ? (searchValue || '') : internalSearch;

    const getCellValue = (row, col) => {
        const value = row?.[col.key];
        if (value == null) return '';
        return typeof value === 'object' ? JSON.stringify(value) : String(value);
    };

    const processedData = useMemo(() => {
        const query = currentSearch.trim().toLowerCase();
        const searchableColumns = columns.filter((col) => col.searchable !== false);
        let rows = Array.isArray(data) ? [...data] : [];

        if (query && onSearch === undefined) {
            rows = rows.filter((row) =>
                searchableColumns.some((col) => getCellValue(row, col).toLowerCase().includes(query))
            );
        }

        if (sortConfig) {
            const col = columns.find((c) => c.key === sortConfig.key) || sortConfig;
            rows.sort((a, b) => {
                const av = getCellValue(a, col);
                const bv = getCellValue(b, col);
                const an = Number(av);
                const bn = Number(bv);
                const result = Number.isFinite(an) && Number.isFinite(bn)
                    ? an - bn
                    : av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
                return sortConfig.direction === 'asc' ? result : -result;
            });
        }

        return rows;
    }, [columns, currentSearch, data, onSearch, sortConfig]);

    const pagination = usePagination(processedData, initialPageSize);
    const displayData = paginate ? pagination.paginatedItems : processedData;
    const tableMinWidth = columns.length > 6 ? Math.max(720, columns.length * 128) : undefined;
    const isActionsColumn = (col) => col.key === 'actions';
    const getStickySide = (col) => col.sticky || (stickyActions && isActionsColumn(col) ? 'end' : null);
    const getFallbackWidth = (col) => {
        if (isActionsColumn(col)) return 132;
        if (col.key === 'tax_code') return 150;
        if (col.key === 'tax_name') return 190;
        return 144;
    };
    const resolveColumnWidth = (col) => {
        const fallback = getFallbackWidth(col);
        if (typeof col.width === 'number') return { css: `${col.width}px`, px: col.width };
        if (typeof col.width === 'string') {
            const match = col.width.trim().match(/^(\d+(?:\.\d+)?)px$/);
            if (match) return { css: col.width, px: Number(match[1]) };
            return { css: col.width, px: fallback };
        }
        return { css: `${fallback}px`, px: fallback };
    };
    const stickyColumns = useMemo(() => {
        const meta = {};
        let startOffset = 0;
        let endOffset = 0;

        columns.forEach((col) => {
            if (getStickySide(col) !== 'start') return;
            const width = resolveColumnWidth(col);
            meta[col.key] = { side: 'start', offset: startOffset, width: width.css };
            startOffset += width.px;
        });

        [...columns].reverse().forEach((col) => {
            if (getStickySide(col) !== 'end') return;
            const width = resolveColumnWidth(col);
            meta[col.key] = { side: 'end', offset: endOffset, width: width.css };
            endOffset += width.px;
        });

        return meta;
    }, [columns, stickyActions]);
    const hasStickyColumns = Object.keys(stickyColumns).length > 0;
    const getColumnClassName = (col) => {
        const classes = [];
        if (isActionsColumn(col)) classes.push('data-table-actions-cell');
        if (stickyColumns[col.key]) classes.push('data-table-sticky-cell', `data-table-sticky-${stickyColumns[col.key].side}`);
        return classes.join(' ') || undefined;
    };
    const getColumnStyle = (col, cellStyle) => {
        const stickyMeta = stickyColumns[col.key];
        if (!isActionsColumn(col) && !stickyMeta) return cellStyle;
        const width = stickyMeta?.width || resolveColumnWidth(col).css;
        const style = { ...cellStyle, width, minWidth: width, maxWidth: width };
        if (stickyMeta) style['--data-table-sticky-offset'] = `${stickyMeta.offset}px`;
        return style;
    };

    const handleSearchChange = (value) => {
        if (onSearch) onSearch(value);
        else setInternalSearch(value);
    };

    const handleSort = (col) => {
        if (!sortable || col.sortable === false) return;
        setSortConfig((prev) => {
            if (!prev || prev.key !== col.key) return { key: col.key, direction: 'asc' };
            if (prev.direction === 'asc') return { key: col.key, direction: 'desc' };
            return null;
        });
    };

    const handleExport = () => {
        const escapeCsv = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
        const exportColumns = columns.filter((col) => col.exportable !== false);
        const header = exportColumns.map((col) => escapeCsv(col.label)).join(',');
        const rows = processedData.map((row) =>
            exportColumns.map((col) => escapeCsv(getCellValue(row, col))).join(',')
        );
        const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${exportName}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    };

    if (loading) return <PageLoading />;

    return (
        <div className={`card card-flush${hasStickyColumns ? ' data-table-has-sticky' : ''}`} style={{ overflow: 'hidden' }}>
            {(searchable || onSearch !== undefined || exportable) && (
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
                    {(searchable || onSearch !== undefined) && (
                        <div style={{ position: 'relative', maxWidth: 360, width: '100%' }}>
                            <Search size={16} style={{ position: 'absolute', insetInlineStart: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                            <input
                                type="text"
                                className="form-input"
                                placeholder={searchPlaceholder || t('common.search', 'بحث...')}
                                value={currentSearch}
                                onChange={(e) => handleSearchChange(e.target.value)}
                                style={{ paddingInlineStart: 34 }}
                            />
                        </div>
                    )}
                    {exportable && (
                        <button className="btn btn-outline btn-sm" type="button" onClick={handleExport}>
                            <Download size={16} /> {t('common.export', 'تصدير')}
                        </button>
                    )}
                </div>
            )}
            <div className="data-table-wrapper">
                <table className="data-table" style={{ minWidth: tableMinWidth }}>
                    <thead>
                        <tr>
                            {columns.map((col) => (
                                <th
                                    key={col.key}
                                    className={getColumnClassName(col)}
                                    style={{
                                        ...getColumnStyle(col, { width: col.width, ...col.headerStyle }),
                                        cursor: sortable && col.sortable !== false ? 'pointer' : undefined,
                                    }}
                                    onClick={() => handleSort(col)}
                                >
                                    <span className="data-table-header-content">
                                        {col.label}
                                        {sortable && col.sortable !== false && <ArrowUpDown size={13} style={{ opacity: sortConfig?.key === col.key ? 1 : 0.35 }} />}
                                    </span>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {processedData.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length}>
                                    <EmptyState
                                        icon={emptyIcon}
                                        title={emptyTitle || (data.length === 0 ? t('common.no_data', 'لا توجد بيانات') : t('common.no_search_results', 'لا توجد نتائج مطابقة'))}
                                        description={emptyDesc}
                                        action={emptyAction}
                                    />
                                </td>
                            </tr>
                        ) : (
                            displayData.map((row) => (
                                <tr
                                    key={row[rowKey]}
                                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                                    style={onRowClick ? { cursor: 'pointer' } : undefined}
                                >
                                    {columns.map((col) => {
                                        const content = col.render ? col.render(row[col.key], row) : row[col.key];
                                        return (
                                            <td
                                                key={col.key}
                                                className={getColumnClassName(col)}
                                                style={getColumnStyle(col, col.style)}
                                            >
                                                {isActionsColumn(col) ? <div className="data-table-actions">{content}</div> : content}
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
            {paginate && processedData.length > 0 && (
                <Pagination
                    currentPage={pagination.currentPage}
                    totalItems={pagination.totalItems}
                    pageSize={pagination.pageSize}
                    onPageChange={pagination.onPageChange}
                    onPageSizeChange={pagination.onPageSizeChange}
                />
            )}
        </div>
    );
}
