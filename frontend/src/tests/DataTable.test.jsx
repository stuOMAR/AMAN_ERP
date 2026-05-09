import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import DataTable from '../components/common/DataTable'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (_key, fallback) => fallback || _key,
        i18n: { language: 'ar' },
    }),
}))

describe('DataTable', () => {
    const columns = [
        { key: 'code', label: 'Code' },
        { key: 'amount', label: 'Amount' },
    ]
    const data = [
        { id: 1, code: 'VAT', amount: '15.00' },
        { id: 2, code: 'WHT', amount: '5.00' },
    ]

    it('filters rows without changing Decimal string values', () => {
        render(<DataTable columns={columns} data={data} searchable />)

        expect(screen.getByText('VAT')).toBeInTheDocument()
        expect(screen.getByText('15.00')).toBeInTheDocument()

        fireEvent.change(screen.getByPlaceholderText('بحث...'), { target: { value: 'WHT' } })

        expect(screen.queryByText('VAT')).not.toBeInTheDocument()
        expect(screen.getByText('WHT')).toBeInTheDocument()
        expect(screen.getByText('5.00')).toBeInTheDocument()
    })

    it('sorts numeric Decimal strings as numbers', () => {
        render(<DataTable columns={columns} data={data} />)

        fireEvent.click(screen.getByText('Amount'))

        const rows = screen.getAllByRole('row')
        expect(rows[1]).toHaveTextContent('WHT')
        expect(rows[2]).toHaveTextContent('VAT')
    })

    it('marks configured columns as sticky without changing cell content', () => {
        render(<DataTable columns={[
            { key: 'code', label: 'Code', width: '120px', sticky: 'start' },
            { key: 'amount', label: 'Amount' },
            { key: 'actions', label: 'Actions', width: '132px', sticky: 'end', render: () => 'Edit' },
        ]} data={data} />)

        expect(screen.getByRole('columnheader', { name: /Code/ })).toHaveClass('data-table-sticky-start')
        expect(screen.getByRole('columnheader', { name: /Actions/ })).toHaveClass('data-table-sticky-end')
        expect(screen.getAllByText('Edit')).toHaveLength(2)
    })
})
