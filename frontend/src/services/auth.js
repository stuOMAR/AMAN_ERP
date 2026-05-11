import api from './apiClient'

export const authAPI = {
    login: (username, password, companyCode) => {
        const formData = new URLSearchParams()
        formData.append('username', username)
        formData.append('password', password)
        if (companyCode) {
            formData.append('company_code', companyCode.trim())
        }
        return api.post('/auth/login', formData, {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        })
    },
    me: (config) => api.get('/auth/me', config),
    updateMe: (data) => api.put('/auth/me', data),
    // SEC-C4b: refresh token travels in the HttpOnly cookie. The backend
    // picks it from the cookie; we no longer read it from localStorage.
    logout: () => api.post('/auth/logout', {}),
    refresh: () => api.post('/auth/refresh', {}),
    getSsoProviders: (companyCode) =>
        api.get('/auth/sso/providers', { params: { company_code: companyCode } }),
    ssoLogin: (ssoConfigurationId, companyCode, username, password) =>
        api.post('/auth/sso/login', {
            sso_configuration_id: ssoConfigurationId,
            company_code: companyCode,
            username,
            password,
        }),
    verify2FALogin: (temp_token, code) =>
        api.post('/auth/2fa/verify-login', { temp_token, code }),
}
