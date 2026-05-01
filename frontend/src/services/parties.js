import api from './apiClient'

export const partiesAPI = {
    getCustomers: (params) => api.get('/parties/customers', { params }),
    getSuppliers: (params) => api.get('/parties/suppliers', { params }),

    // T7.3: phone-based duplicate detection across customers/suppliers/parties.
    // Strips non-digits server-side and looks up the `phone_clean` STORED column.
    getDuplicatesByPhone: (phone, limit = 50) =>
        api.get('/parties/duplicates-by-phone', {
            params: { phone, limit },
            skipGlobalToast: true,
        }),
}
