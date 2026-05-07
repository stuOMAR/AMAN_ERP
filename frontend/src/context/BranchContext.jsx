import React, { createContext, useContext, useState, useEffect } from 'react';
import { branchesAPI } from '../utils/api';
import { getToken } from '../utils/tokenStore';
import { getUser, getCurrency, getCompanyCurrency, setDisplayCurrency } from '../utils/auth';

const BranchContext = createContext();

export const useBranch = () => {
    const context = useContext(BranchContext);
    if (!context) {
        throw new Error('useBranch must be used within a BranchProvider');
    }
    return context;
};

const normalizeCurrency = (value) => String(value || '').trim().toUpperCase();

const resolveDisplayCurrency = (currentBranch, branches) => {
    const baseCurrency = normalizeCurrency(getCompanyCurrency() || getCurrency());

    if (currentBranch) {
        const currency = normalizeCurrency(currentBranch.default_currency) || baseCurrency;
        return {
            currency,
            baseCurrency,
            mode: 'branch',
            isMultiCurrencyScope: false,
            currencies: currency ? [currency] : [],
        };
    }

    const scopedCurrencies = Array.from(new Set(
        (branches || [])
            .map(branch => normalizeCurrency(branch.default_currency) || baseCurrency)
            .filter(Boolean)
    ));

    if (scopedCurrencies.length === 1) {
        return {
            currency: scopedCurrencies[0],
            baseCurrency,
            mode: 'branches_same_currency',
            isMultiCurrencyScope: false,
            currencies: scopedCurrencies,
        };
    }

    const mainBranch = (branches || []).find(branch => branch.is_default) || (branches || [])[0];
    const mainBranchCurrency = normalizeCurrency(mainBranch?.default_currency) || baseCurrency;

    return {
        currency: mainBranchCurrency,
        baseCurrency,
        mode: scopedCurrencies.length > 1 ? 'main_branch_consolidated' : 'company_base',
        isMultiCurrencyScope: scopedCurrencies.length > 1,
        currencies: scopedCurrencies,
    };
};

const persistDisplayCurrency = (currentBranch, branches) => {
    const displayCurrency = resolveDisplayCurrency(currentBranch, branches);
    setDisplayCurrency(displayCurrency.currency, displayCurrency);
    return displayCurrency;
};

export const useDisplayCurrency = () => {
    const { displayCurrency } = useBranch();
    return displayCurrency;
};

/**
 * Get the effective display currency for the selected branch scope.
 * Falls back to company base currency from auth.
 */
export const useBranchCurrency = () => {
    const { displayCurrency } = useBranch();
    return displayCurrency.currency;
};

export const BranchProvider = ({ children }) => {
    const [branches, setBranches] = useState([]);
    const [currentBranch, setCurrentBranch] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchBranches = async () => {
        try {
            const res = await branchesAPI.list();
            setBranches(res.data);

            const user = getUser();
            const isAdmin = user?.role === 'admin' || user?.role === 'superuser' || user?.role === 'system_admin' || user?.permissions?.includes('*');

            const savedBranchId = localStorage.getItem('current_branch_id');
            let branchToSet = null;

            if (isAdmin) {
                // Admin: default ALL unless specific branch saved
                if (savedBranchId && savedBranchId !== 'all') {
                    branchToSet = res.data.find(b => b.id === parseInt(savedBranchId)) || null;
                } else {
                    branchToSet = null;
                }
            } else if (res.data.length > 1) {
                // Non-admin with multiple branches: respect saved preference (including 'all my branches')
                if (savedBranchId === 'all') {
                    branchToSet = null; // "all my branches" — backend filters by user access
                } else if (savedBranchId) {
                    branchToSet = res.data.find(b => b.id === parseInt(savedBranchId)) || res.data[0];
                } else {
                    branchToSet = res.data[0];
                }
            } else {
                // Non-admin with single branch: always pin to that branch
                branchToSet = res.data[0] || null;
            }

            persistDisplayCurrency(branchToSet, res.data);
            setCurrentBranch(branchToSet);
            if (branchToSet) {
                localStorage.setItem('current_branch_id', branchToSet.id);
            } else {
                localStorage.setItem('current_branch_id', 'all');
            }

        } catch (error) {
            console.error('Error fetching branches for context:', error);
            persistDisplayCurrency(null, []);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        // Only fetch after bootstrapAuth completes and sets the in-memory token.
        // Do NOT call fetchBranches() on mount — token is not yet available.
        const onAuthReady = () => {
            if (getToken()) fetchBranches();
            else setLoading(false);
        };
        window.addEventListener('auth:ready', onAuthReady);
        return () => window.removeEventListener('auth:ready', onAuthReady);
    }, []);

    const setBranch = (branch) => {
        persistDisplayCurrency(branch, branches);
        setCurrentBranch(branch);
        if (branch) {
            localStorage.setItem('current_branch_id', branch.id);
        } else {
            localStorage.setItem('current_branch_id', 'all');
        }
        window.dispatchEvent(new CustomEvent('branch:changed', {
            detail: { branchId: branch?.id || null }
        }));
    };

    const displayCurrency = resolveDisplayCurrency(currentBranch, branches);

    return (
        <BranchContext.Provider value={{ branches, currentBranch, setBranch, loading, refreshBranches: fetchBranches, displayCurrency }}>
            {children}
        </BranchContext.Provider>
    );
};
