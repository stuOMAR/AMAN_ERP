/**
 * AMAN ERP - High-Precision Decimal Utility
 * Uses BigInt with a fixed scale of 12 decimal places to guarantee
 * absolute mathematical precision with round-half-up for commercial arithmetic.
 */

const SCALE = 12n;
const ONE = 10n ** SCALE;

export class Decimal {
    constructor(value) {
        if (value instanceof Decimal) {
            this.bi = value.bi;
            return;
        }
        if (value === null || value === undefined || value === '') {
            this.bi = 0n;
            return;
        }
        let str = String(value).trim();
        if (str === '') {
            this.bi = 0n;
            return;
        }
        
        let isNegative = false;
        if (str.startsWith('-')) {
            isNegative = true;
            str = str.slice(1);
        }
        
        let [intPart, fracPart = ''] = str.split('.');
        intPart = intPart.replace(/^0+/, '') || '0';
        
        // Clean non-numeric characters if any (e.g. currency separators)
        intPart = intPart.replace(/[^\d]/g, '');
        fracPart = fracPart.replace(/[^\d]/g, '');
        
        fracPart = fracPart.slice(0, Number(SCALE));
        fracPart = fracPart + '0'.repeat(Number(SCALE) - fracPart.length);
        
        let bi = BigInt(intPart) * ONE + BigInt(fracPart);
        if (isNegative) {
            bi = -bi;
        }
        this.bi = bi;
    }

    static from(val) {
        return new Decimal(val);
    }

    add(other) {
        const o = new Decimal(other);
        const res = new Decimal(0);
        res.bi = this.bi + o.bi;
        return res;
    }

    sub(other) {
        const o = new Decimal(other);
        const res = new Decimal(0);
        res.bi = this.bi - o.bi;
        return res;
    }

    mul(other) {
        const o = new Decimal(other);
        const res = new Decimal(0);
        let prod = this.bi * o.bi;
        let sign = prod < 0n ? -1n : 1n;
        let absProd = prod < 0n ? -prod : prod;
        let rounded = (absProd + (ONE / 2n)) / ONE;
        res.bi = rounded * sign;
        return res;
    }

    div(other) {
        const o = new Decimal(other);
        if (o.bi === 0n) throw new Error('Division by zero');
        const res = new Decimal(0);
        let num = this.bi * ONE;
        let den = o.bi;
        let sign = (num < 0n ^ den < 0n) ? -1n : 1n;
        let absNum = num < 0n ? -num : num;
        let absDen = den < 0n ? -den : den;
        let rounded = (absNum + (absDen / 2n)) / absDen;
        res.bi = rounded * sign;
        return res;
    }

    toFixed(precision = 2) {
        let bi = this.bi;
        let sign = bi < 0n ? '-' : '';
        let absBi = bi < 0n ? -bi : bi;

        let diff = Number(SCALE) - precision;
        if (diff > 0) {
            let divisor = 10n ** BigInt(diff);
            let half = divisor / 2n;
            absBi = (absBi + half) / divisor;
        } else if (diff < 0) {
            absBi = absBi * (10n ** BigInt(-diff));
        }

        let str = absBi.toString();
        if (precision === 0) {
            return sign + str;
        }
        if (str.length <= precision) {
            str = '0'.repeat(precision - str.length + 1) + str;
        }
        let intPart = str.slice(0, str.length - precision);
        let fracPart = str.slice(str.length - precision);
        return sign + intPart + '.' + fracPart;
    }

    toString() {
        return this.toFixed(2);
    }
}
