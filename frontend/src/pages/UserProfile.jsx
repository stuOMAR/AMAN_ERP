import { useState, useEffect } from 'react'
import { authAPI, securityAPI } from '../utils/api'
import { getUser, getCompanyId, updateUser } from '../utils/auth'
import { useTranslation } from 'react-i18next'
import BackButton from '../components/common/BackButton'
import { PageLoading } from '../components/common/LoadingStates'

function UserProfile() {
    const { t } = useTranslation()
    const [user, setUser] = useState(null)
    const [profileForm, setProfileForm] = useState({ full_name: '', email: '' })
    const [passwordForm, setPasswordForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
    const [showPasswords, setShowPasswords] = useState({ current: false, next: false, confirm: false })
    const [savingProfile, setSavingProfile] = useState(false)
    const [savingPassword, setSavingPassword] = useState(false)
    const [profileMessage, setProfileMessage] = useState('')
    const [passwordMessage, setPasswordMessage] = useState('')
    const [profileError, setProfileError] = useState('')
    const [passwordError, setPasswordError] = useState('')
    const [sessions, setSessions] = useState([])
    const [loadingSessions, setLoadingSessions] = useState(false)
    const companyId = getCompanyId()

    useEffect(() => {
        const currentUser = getUser()
        setUser(currentUser)
        setProfileForm({
            full_name: currentUser?.full_name || '',
            email: currentUser?.email || ''
        })
        fetchSessions()
    }, [])

    const fetchSessions = async () => {
        setLoadingSessions(true)
        try {
            const res = await securityAPI.listSessions()
            const payload = res?.data
            const normalizedSessions = Array.isArray(payload)
                ? payload
                : Array.isArray(payload?.sessions)
                    ? payload.sessions
                    : []
            setSessions(normalizedSessions)
        } catch {
            setSessions([])
        } finally {
            setLoadingSessions(false)
        }
    }

    const handleTerminateSession = async (sessionId) => {
        try {
            await securityAPI.terminateSession(sessionId)
            setSessions(prev => prev.filter(s => s.id !== sessionId))
        } catch {
            // silently ignore
        }
    }

    const handleProfileSave = async (e) => {
        e.preventDefault()
        setProfileError('')
        setProfileMessage('')

        const fullName = profileForm.full_name.trim()
        const email = profileForm.email.trim()

        if (!fullName) {
            setProfileError(t('common.profile_page.full_name_required'))
            return
        }

        setSavingProfile(true)
        try {
            const response = await authAPI.updateMe({ full_name: fullName, email: email || null })
            const updated = response.data
            setUser(updated)
            updateUser({
                full_name: updated.full_name,
                email: updated.email
            })
            setProfileMessage(t('common.profile_page.profile_saved'))
        } catch (err) {
            setProfileError(err.response?.data?.detail || t('common.profile_page.profile_save_failed'))
        } finally {
            setSavingProfile(false)
        }
    }

    const handlePasswordSave = async (e) => {
        e.preventDefault()
        setPasswordError('')
        setPasswordMessage('')

        if (passwordForm.new_password !== passwordForm.confirm_password) {
            setPasswordError(t('common.profile_page.password_mismatch'))
            return
        }
        if (passwordForm.new_password.length < 8) {
            setPasswordError(t('common.profile_page.password_too_short'))
            return
        }

        setSavingPassword(true)
        try {
            await securityAPI.changePassword({
                current_password: passwordForm.current_password,
                new_password: passwordForm.new_password
            })
            setPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
            setPasswordMessage(t('common.profile_page.password_saved'))
        } catch (err) {
            setPasswordError(err.response?.data?.detail || t('common.profile_page.password_save_failed'))
        } finally {
            setSavingPassword(false)
        }
    }

    const togglePasswordVisibility = (key) => {
        setShowPasswords((prev) => ({ ...prev, [key]: !prev[key] }))
    }

    if (!user) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header" style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <BackButton />
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h1 className="workspace-title">{t('common.profile_page.title')}</h1>
                    <p className="workspace-subtitle">{t('common.profile_page.subtitle')}</p>
                </div>
            </div>

            <div className="card" style={{ maxWidth: '680px' }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '32px' }}>
                    <div style={{
                        width: '80px',
                        height: '80px',
                        borderRadius: '50%',
                        backgroundColor: 'var(--primary)',
                        color: 'white',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '32px',
                        fontWeight: 'bold',
                        marginLeft: '24px'
                    }}>
                        {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                        <h2 style={{ fontSize: '24px', margin: '0 0 8px 0' }}>{user.full_name}</h2>
                        <span className="badge badge-primary">{user.role}</span>
                    </div>
                </div>

                <form onSubmit={handleProfileSave}>
                    {profileError && <div className="alert alert-error">{profileError}</div>}
                    {profileMessage && <div className="alert" style={{ background: 'rgba(16, 185, 129, 0.12)', color: 'var(--success)', border: '1px solid rgba(16, 185, 129, 0.25)' }}>{profileMessage}</div>}

                    <div className="form-group mb-4">
                        <div className="form-label">{t('common.profile_page.username')}</div>
                        <div style={{ padding: '12px', background: 'var(--bg-hover)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                            {user.username}
                        </div>
                    </div>

                    <div className="form-group mb-4">
                        <label className="form-label" htmlFor="full_name_input">{t('common.profile_page.full_name')}</label>
                        <input
                            id="full_name_input"
                            className="form-input"
                            value={profileForm.full_name}
                            onChange={(e) => setProfileForm((prev) => ({ ...prev, full_name: e.target.value }))}
                            required
                        />
                    </div>

                    <div className="form-group mb-4">
                        <label className="form-label" htmlFor="email_input">{t('common.profile_page.email')}</label>
                        <input
                            id="email_input"
                            type="email"
                            className="form-input"
                            placeholder={t('common.profile_page.not_set')}
                            value={profileForm.email}
                            onChange={(e) => setProfileForm((prev) => ({ ...prev, email: e.target.value }))}
                        />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '24px' }}>
                        <button type="submit" className="btn btn-primary" disabled={savingProfile}>
                            {savingProfile ? t('common.saving') : t('common.save')}
                        </button>
                    </div>
                </form>

                <hr style={{ border: 0, borderTop: '1px solid var(--border-color)', margin: '8px 0 24px 0' }} />

                <form onSubmit={handlePasswordSave}>
                    <h3 style={{ marginBottom: '16px' }}>{t('common.profile_page.change_password')}</h3>
                    {passwordError && <div className="alert alert-error">{passwordError}</div>}
                    {passwordMessage && <div className="alert" style={{ background: 'rgba(16, 185, 129, 0.12)', color: 'var(--success)', border: '1px solid rgba(16, 185, 129, 0.25)' }}>{passwordMessage}</div>}

                    <div className="form-group mb-4">
                        <label className="form-label" htmlFor="current_password_input">{t('common.profile_page.current_password')}</label>
                        <div className="input-group">
                            <input
                                id="current_password_input"
                                type={showPasswords.current ? 'text' : 'password'}
                                className="form-input"
                                value={passwordForm.current_password}
                                onChange={(e) => setPasswordForm((prev) => ({ ...prev, current_password: e.target.value }))}
                                required
                            />
                            <button className="btn btn-light" type="button" onClick={() => togglePasswordVisibility('current')}>
                                {showPasswords.current ? t('common.hide') : t('common.show')}
                            </button>
                        </div>
                    </div>

                    <div className="form-group mb-4">
                        <label className="form-label" htmlFor="new_password_input">{t('common.profile_page.new_password')}</label>
                        <div className="input-group">
                            <input
                                id="new_password_input"
                                type={showPasswords.next ? 'text' : 'password'}
                                className="form-input"
                                value={passwordForm.new_password}
                                onChange={(e) => setPasswordForm((prev) => ({ ...prev, new_password: e.target.value }))}
                                required
                                minLength={8}
                            />
                            <button className="btn btn-light" type="button" onClick={() => togglePasswordVisibility('next')}>
                                {showPasswords.next ? t('common.hide') : t('common.show')}
                            </button>
                        </div>
                    </div>

                    <div className="form-group mb-4">
                        <label className="form-label" htmlFor="confirm_password_input">{t('common.profile_page.confirm_password')}</label>
                        <div className="input-group">
                            <input
                                id="confirm_password_input"
                                type={showPasswords.confirm ? 'text' : 'password'}
                                className="form-input"
                                value={passwordForm.confirm_password}
                                onChange={(e) => setPasswordForm((prev) => ({ ...prev, confirm_password: e.target.value }))}
                                required
                            />
                            <button className="btn btn-light" type="button" onClick={() => togglePasswordVisibility('confirm')}>
                                {showPasswords.confirm ? t('common.hide') : t('common.show')}
                            </button>
                        </div>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <button type="submit" className="btn btn-primary" disabled={savingPassword}>
                            {savingPassword ? t('common.saving') : t('common.profile_page.save_password')}
                        </button>
                    </div>
                </form>

                {companyId && (
                    <div className="form-group mb-4">
                        <div className="form-label">{t('common.profile_page.company_id')}</div>
                        <div style={{ padding: '12px', background: 'var(--bg-hover)', borderRadius: '8px', border: '1px solid var(--border-color)', fontFamily: 'monospace' }}>
                            {companyId}
                        </div>
                    </div>
                )}

                <hr style={{ border: 0, borderTop: '1px solid var(--border-color)', margin: '8px 0 24px 0' }} />

                <h3 style={{ marginBottom: '16px' }}>{t('common.profile_page.active_sessions')}</h3>
                {loadingSessions ? (
                    <PageLoading />
                ) : !Array.isArray(sessions) || sessions.length === 0 ? (
                    <p style={{ color: '#888', fontSize: '14px' }}>{t('common.profile_page.no_sessions')}</p>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('common.profile_page.ip_address')}</th>
                                    <th>{t('common.profile_page.device')}</th>
                                    <th>{t('common.profile_page.last_active')}</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {sessions.map(session => (
                                    <tr key={session.id}>
                                        <td><code>{session.ip_address || '—'}</code></td>
                                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{session.user_agent || '—'}</td>
                                        <td>{session.last_active || session.created_at || '—'}</td>
                                        <td>
                                            <button
                                                className="btn btn-sm btn-outline"
                                                style={{ color: 'var(--danger)' }}
                                                onClick={() => handleTerminateSession(session.id)}
                                            >
                                                {t('common.profile_page.terminate')}
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    )
}

export default UserProfile
