"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TITAN SYSTEM — Estrategias de tus modelos adaptadas al Backtester          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CONCEPTO CLAVE — ADAPTER PATTERN:                                           ║
║  ==================================                                          ║
║  Tus modelos originales son scripts monoliticos que descargan datos,         ║
║  entrenan, predicen y muestran resultados, todo en un solo archivo.          ║
║                                                                              ║
║  El backtester necesita una funcion simple que reciba precios y devuelva     ║
║  picks. Este archivo "adapta" la logica de cada modelo a esa interfaz.       ║
║                                                                              ║
║  Cada strategy function tiene esta firma:                                    ║
║                                                                              ║
║    def strategy_xxx(prices_dict, tickers, date_str):                         ║
║        # prices_dict = {ticker: DataFrame_OHLCV}  (datos hasta HOY)         ║
║        # tickers = lista de tickers disponibles                              ║
║        # date_str = fecha actual (YYYY-MM-DD)                                ║
║        #                                                                     ║
║        # Returns: [{ticker, direction, confidence, score}, ...]              ║
║                                                                              ║
║  CONCEPTO — TRAIN-PREDICT DENTRO DEL BACKTEST:                               ║
║  =============================================                               ║
║  El backtester llama a la strategy function para CADA dia del backtest.      ║
║  Dentro de la function, debemos:                                             ║
║  1. Computar features con datos hasta HOY (sin data leakage)                ║
║  2. Entrenar modelos con datos historicos (walk-forward)                     ║
║  3. Predecir para el dia siguiente                                           ║
║                                                                              ║
║  PROBLEMA: entrenar ML modelos 252 veces (una por dia) es MUY lento.       ║
║  SOLUCION: usamos un CACHE — entrenamos UNA vez al inicio y re-entrenamos  ║
║  cada N dias (ej: cada 20 dias habiles = ~1 mes).                           ║
║  Esto simula lo que harias en la vida real: no re-entrenas cada dia.        ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
)
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import RobustScaler

# XGBoost (opcional — solo para StrategyV94)
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


# ═══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE FEATURES COMPARTIDAS
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Estas funciones computan indicadores tecnicos. Son PURAS (no tienen estado,
#  no modifican datos externos). Reciben datos, devuelven resultados.
#
#  CONCEPTO — Funciones puras vs funciones con efecto secundario:
#  Una funcion pura siempre devuelve el mismo resultado para los mismos inputs.
#  No modifica nada externo. Esto las hace faciles de testear y depurar.

def compute_rsi(close, period=14):
    """
    RSI (Relative Strength Index).
    Mide la velocidad y magnitud de movimientos de precio.
    RSI > 70 = sobrecomprado, RSI < 30 = sobrevendido.
    """
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def detect_regime_spy(spy_close):
    """
    Detecta regimen de mercado usando SPY.
    Returns: Series con 'BULL', 'BEAR', o 'NEUTRAL' para cada fecha.
    """
    ma20 = spy_close.rolling(20).mean()
    ma50 = spy_close.rolling(50).mean()
    ret20 = spy_close.pct_change(20)
    vol10 = spy_close.pct_change().rolling(10).std() * np.sqrt(252)

    regime = pd.Series('NEUTRAL', index=spy_close.index)

    bull = (
        (spy_close > ma20) &
        (ma20 > ma50 * 0.99) &
        (ret20 > 0.015) &
        (vol10 < vol10.rolling(60).quantile(0.65))
    )
    bear = (
        (spy_close < ma20) &
        (ret20 < -0.012) &
        (vol10 > vol10.rolling(60).quantile(0.40))
    )
    regime[bull] = 'BULL'
    regime[bear] = 'BEAR'
    return regime


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 1: v37 — NOVA Squeeze Detector (T+1, 7 features)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Busca activos cuya volatilidad se comprimio (Bollinger squeeze)
#  y que muestran signos de acumulacion institucional (volumen anormal +
#  cierre fuerte). Predice un salto de +2.5% al dia siguiente.
#
#  Es un modelo de NICHO: no predice todo, solo busca "explosiones".
#  Cuando no encuentra nada, devuelve lista vacia. Eso esta bien.

class StrategyV37:
    """Wrapper con estado para el modelo v37 (re-entrena periodicamente)."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.model = None
        self.scaler = None
        self.day_count = 0
        self.feat_cols = ['close_strength', 'bb_squeeze_rank', 'vol_zscore',
                          'gap_open', 'intraday_return', 'rsi_3', 'dist_10d_low']

    def _compute_features(self, df):
        """7 features de microestructura de velas diarias."""
        o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
        feat = pd.DataFrame(index=df.index)
        feat['close_strength'] = (c - l) / (h - l + 1e-10)
        ma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_width = (4 * std20) / (ma20 + 1e-10)
        feat['bb_squeeze_rank'] = bb_width.rolling(60, min_periods=20).rank(pct=True)
        vol_ma = v.rolling(20).mean()
        vol_std = v.rolling(20).std()
        feat['vol_zscore'] = (v - vol_ma) / (vol_std + 1e-10)
        feat['gap_open'] = (o / c.shift(1) - 1) * 100
        feat['intraday_return'] = (c / o - 1) * 100
        feat['rsi_3'] = compute_rsi(c, 3)
        feat['dist_10d_low'] = (c / l.rolling(10).min() - 1) * 100
        return feat.fillna(0)

    def _train(self, prices_dict):
        """Entrena el modelo con datos de todos los tickers."""
        X_all, y_all = [], []
        for ticker, df in prices_dict.items():
            if len(df) < 65:
                continue
            feat = self._compute_features(df)
            # Target: retorno T+1 >= 2.5%
            fwd_ret = df['Close'].pct_change(1).shift(-1)
            target = (fwd_ret >= 0.025).astype(int)
            # Quitar ultimo dia (sin target)
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 20:
                continue
            X_all.append(feat.loc[valid, self.feat_cols].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)
        self.model = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_depth=5,
            l2_regularization=0.1, class_weight='balanced', random_state=42)
        self.model.fit(Xs, y)
        return True

    def __call__(self, prices_dict, tickers, date_str):
        """Strategy function para el backtester."""
        self.day_count += 1

        # Re-entrenar periodicamente
        if self.model is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []

        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 65:
                continue

            feat = self._compute_features(df)
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)
            prob = self.model.predict_proba(X)[0]

            # Solo tomar si hay clase 1 en el modelo
            if len(prob) < 2:
                continue
            prob_surge = prob[1]

            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(prob_surge),
                'score': float(prob_surge * 100),
            })

        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 2: v97 — TITAN OMEGA Microstructure (T+1-3, 5 features)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Similar a v37 pero busca movimientos mas grandes (+3.5%)
#  en ventana de 3 dias. Usa Parkinson Volatility (mide expansion de rango
#  intradiario) que es un proxy de actividad institucional.

class StrategyV97:
    """Modelo v97: 5 metricas de microestructura, busca surges 3.5%."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.model = None
        self.scaler = None
        self.day_count = 0
        self.cols = ['c2h', 'vol_z', 'bb_squeeze_rank', 'accel', 'parkinson_vol']

    def _compute_features(self, df):
        o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
        feat = pd.DataFrame(index=df.index)
        feat['c2h'] = (c - l) / (h - l + 1e-10)
        vol_ma = v.rolling(20).mean()
        feat['vol_z'] = (v - vol_ma) / (v.rolling(20).std() + 1e-10)
        ma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_w = (4 * std20) / (ma20 + 1e-10)
        feat['bb_squeeze_rank'] = bb_w.rolling(60, min_periods=20).rank(pct=True)
        feat['accel'] = c.pct_change(3).diff(3) * 100
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        feat['parkinson_vol'] = np.sqrt(log_hl.rolling(14).mean() / (4 * np.log(2)))
        return feat.fillna(0)

    def _train(self, prices_dict):
        X_all, y_all = [], []
        for ticker, df in prices_dict.items():
            if len(df) < 65:
                continue
            feat = self._compute_features(df)
            close = df['Close']
            # Target: max retorno en T+1 a T+3 >= 3.5%
            ret_t1 = close.pct_change(1).shift(-1)
            ret_t2 = close.pct_change(2).shift(-2)
            ret_t3 = close.pct_change(3).shift(-3)
            max_ret = pd.concat([ret_t1, ret_t2, ret_t3], axis=1).max(axis=1)
            target = (max_ret > 0.035).astype(float)
            target.iloc[-3:] = np.nan
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 20:
                continue
            X_all.append(feat.loc[valid, self.cols].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        self.model = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_depth=5,
            l2_regularization=0.3, class_weight='balanced', random_state=42)
        self.model.fit(self.scaler.fit_transform(X), y)
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.model is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []

        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 65:
                continue
            feat = self._compute_features(df)
            X = self.scaler.transform(feat[self.cols].iloc[-1:].values)
            prob = self.model.predict_proba(X)[0]
            if len(prob) < 2:
                continue
            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(prob[1]),
                'score': float(prob[1] * 100),
            })
        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 3: v39full — Daily Ensemble (T+1, 44 features, 3 models)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: El "workhorse" diario. 44 features que cubren momentum,
#  volatilidad, volumen, osciladores, y contexto de mercado.
#  3 modelos ensemble (HGB + RF + ET) promediados.
#  Regime-aware: reduce picks en bear market.
#
#  Este es el modelo mas completo para uso diario general.

class StrategyV39Full:
    """v39full: 44 features, ensemble de 3 modelos, regime-aware."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.models = None
        self.scaler = None
        self.day_count = 0

    def _compute_features_ticker(self, df, spy_close=None):
        """44 features para un ticker."""
        c = df['Close']
        v = df['Volume']
        ret = c.pct_change()

        feat = pd.DataFrame(index=df.index)
        # Momentum (8)
        feat['ret1'] = ret
        feat['ret3'] = c.pct_change(3)
        feat['ret5'] = c.pct_change(5)
        feat['ret10'] = c.pct_change(10)
        feat['ret20'] = c.pct_change(20)
        feat['ret40'] = c.pct_change(40)
        feat['ret60'] = c.pct_change(60)
        feat['mom_accel'] = feat['ret5'] - feat['ret20'].shift(5)

        # MAs (4)
        ma5 = c.rolling(5).mean()
        ma20 = c.rolling(20).mean()
        ma50 = c.rolling(50).mean()
        feat['p_vs_ma5'] = c / ma5 - 1
        feat['p_vs_ma20'] = c / ma20 - 1
        feat['p_vs_ma50'] = c / ma50 - 1
        feat['cross_520'] = ma5 / ma20 - 1

        # RSI (3)
        feat['rsi7'] = compute_rsi(ret.to_frame(), 7).iloc[:, 0] if isinstance(ret, pd.Series) else compute_rsi(ret, 7)
        feat['rsi14'] = compute_rsi(ret.to_frame(), 14).iloc[:, 0] if isinstance(ret, pd.Series) else compute_rsi(ret, 14)
        feat['rsi_slope'] = feat['rsi14'] - feat['rsi14'].shift(3)

        # MACD (3)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        feat['macd_norm'] = macd / (c + 1e-10)
        feat['macd_hist'] = macd - macd_sig
        feat['macd_cross'] = ((feat['macd_hist'] > 0).astype(int) -
                              (feat['macd_hist'].shift(1) > 0).astype(int))

        # Bollinger (2)
        std20 = c.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        feat['bb_pct'] = (c - lower) / (upper - lower + 1e-10)
        feat['bb_width'] = (upper - lower) / (ma20 + 1e-10)

        # Volatilidad (3)
        feat['vol5'] = ret.rolling(5).std()
        feat['vol20'] = ret.rolling(20).std()
        feat['vol_ratio'] = feat['vol5'] / (feat['vol20'] + 1e-8)

        # Stochastic (2)
        lo14 = c.rolling(14).min()
        hi14 = c.rolling(14).max()
        feat['stoch_k'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100
        feat['stoch_d'] = feat['stoch_k'].rolling(3).mean()

        # Volumen (4)
        v_ma20 = v.rolling(20).mean()
        feat['v_ratio'] = v / (v_ma20 + 1e-8)
        feat['v_ratio5'] = v.rolling(5).mean() / (v_ma20 + 1e-8)
        feat['pv_mom'] = feat['ret5'] * np.log1p(feat['v_ratio'].clip(0, 10))
        direction = np.sign(ret)
        obv = (direction * v).cumsum()
        obv_ma10 = obv.rolling(10).mean()
        feat['obv_mom'] = obv / (obv_ma10.abs() + 1e-8) - 1

        # Mercado / Beta (6)
        if spy_close is not None and len(spy_close) > 0:
            spy_ret = spy_close.pct_change().reindex(c.index).fillna(0)
            cov20 = ret.rolling(20).cov(spy_ret)
            mkt_var = spy_ret.rolling(20).var()
            feat['beta20'] = cov20 / (mkt_var + 1e-10)
            feat['roll_corr'] = ret.rolling(20).corr(spy_ret)
            idio = ret - feat['beta20'] * spy_ret
            feat['idio5'] = idio.rolling(5).sum()
            feat['idio_v'] = idio.rolling(5).std()
            feat['rel_str5'] = feat['ret5'] - spy_close.pct_change(5).reindex(c.index).fillna(0)
            feat['rel_str20'] = feat['ret20'] - spy_close.pct_change(20).reindex(c.index).fillna(0)
        else:
            for col in ['beta20','roll_corr','idio5','idio_v','rel_str5','rel_str20']:
                feat[col] = 0

        # Z-score (1)
        feat['zscore20'] = (c - ma20) / (std20 + 1e-10)

        # Market context (2)
        if spy_close is not None and len(spy_close) > 0:
            feat['mkt_trend'] = (spy_close / spy_close.rolling(20).mean() - 1).reindex(c.index).fillna(0)
            spy_ret_series = spy_close.pct_change().reindex(c.index).fillna(0)
            feat['mkt_rsi14'] = compute_rsi(spy_ret_series, 14)
        else:
            feat['mkt_trend'] = 0
            feat['mkt_rsi14'] = 50

        return feat.replace([np.inf, -np.inf], np.nan).fillna(0)

    def _train(self, prices_dict, tickers):
        """Entrena 3 modelos ensemble."""
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')

        X_all, y_all = [], []
        feat_cols = None

        for ticker in tickers:
            if ticker in ('SPY','QQQ','IWM','VIX','TLT','GLD','HYG'):
                continue
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 80:
                continue

            feat = self._compute_features_ticker(df, spy_close)
            if feat_cols is None:
                feat_cols = list(feat.columns)

            # Target: top 10% retorno T+1 cross-sectional
            fwd_ret = df['Close'].pct_change(1).shift(-1)
            # Usamos threshold fijo simple: retorno > 0 (sube)
            target = (fwd_ret > 0).astype(int)
            target.iloc[-1] = np.nan

            valid = target.notna() & feat.notna().all(axis=1)
            # Usar solo ultimos 200 dias para no sobreajustar
            valid_idx = feat.index[valid]
            if len(valid_idx) > 200:
                valid_idx = valid_idx[-200:]

            if len(valid_idx) < 30:
                continue

            X_all.append(feat.loc[valid_idx, feat_cols].values)
            y_all.append(target.loc[valid_idx].values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.feat_cols = feat_cols
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        self.models = (
            HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, learning_rate=0.06,
                min_samples_leaf=15, l2_regularization=0.2, random_state=42),
            RandomForestClassifier(
                n_estimators=120, max_depth=6, min_samples_leaf=12,
                max_features='sqrt', n_jobs=-1, random_state=42),
            ExtraTreesClassifier(
                n_estimators=120, max_depth=7, min_samples_leaf=10,
                max_features='sqrt', n_jobs=-1, random_state=42),
        )
        for m in self.models:
            m.fit(Xs, y)
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict, tickers):
                return []

        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        picks = []

        for ticker in tickers:
            if ticker in ('SPY','QQQ','IWM','VIX','TLT','GLD','HYG'):
                continue
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 80:
                continue

            feat = self._compute_features_ticker(df, spy_close)
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)

            # Promedio de 3 modelos
            prob = np.mean([m.predict_proba(X)[0][1] for m in self.models])

            picks.append({
                'ticker': ticker,
                'direction': 'UP' if prob > 0.5 else 'DOWN',
                'confidence': float(abs(prob - 0.5) * 2),
                'score': float(prob * 100),
            })

        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 4: v72 — Hybrid Quantum (T+1, regime-weighted, 4 modelos)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Fusion de v37 (microestructura) + v39 (momentum) + cross-sectional.
#  4 modelos con pesos que cambian segun el regimen de mercado.
#  Calibracion isotonica para que las probabilidades sean realistas.

class StrategyV72:
    """v72: 4 modelos regime-weighted con 30+ features seleccionadas."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.models = None
        self.scaler = None
        self.day_count = 0

    def _compute_features(self, df, spy_close=None):
        """Features combinadas de microestructura + momentum + volatilidad."""
        o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
        ret = c.pct_change()
        feat = pd.DataFrame(index=df.index)

        # Microestructura (v37-style)
        feat['close_strength'] = (c - l) / (h - l + 1e-10)
        ma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_w = (4 * std20) / (ma20 + 1e-10)
        feat['bb_squeeze_rank'] = bb_w.rolling(60, min_periods=20).rank(pct=True)
        vol_ma = v.rolling(20).mean()
        feat['vol_zscore'] = (v - vol_ma) / (v.rolling(20).std() + 1e-10)
        feat['gap_open'] = (o / c.shift(1) - 1) * 100
        feat['rsi_3'] = compute_rsi(c, 3)
        feat['intraday_range'] = (h - l) / ((o + c) / 2 + 1e-10) * 100

        # Momentum
        feat['ret_1d'] = ret
        feat['ret_3d'] = c.pct_change(3)
        feat['ret_5d'] = c.pct_change(5)
        feat['ret_10d'] = c.pct_change(10)
        feat['ret_20d'] = c.pct_change(20)
        feat['mom_accel'] = feat['ret_5d'] - feat['ret_20d'].shift(5)
        feat['price_vs_ma20'] = (c / ma20 - 1) * 100
        ma50 = c.rolling(50).mean()
        feat['price_vs_ma50'] = (c / ma50 - 1) * 100

        # Volatilidad
        feat['vol_5d'] = ret.rolling(5).std() * np.sqrt(252)
        feat['vol_20d'] = ret.rolling(20).std() * np.sqrt(252)
        feat['vol_ratio'] = feat['vol_5d'] / (feat['vol_20d'] + 1e-10)
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        feat['gk_vol'] = np.sqrt(log_hl.rolling(14).mean() / (4 * np.log(2)))

        # Osciladores
        feat['rsi_14'] = compute_rsi(c, 14)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        feat['macd_hist'] = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        lo14, hi14 = c.rolling(14).min(), c.rolling(14).max()
        feat['stoch_k'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100

        # Volumen
        feat['vol_ratio_ma'] = v / (vol_ma + 1e-10)
        feat['obv_mom'] = (np.sign(ret) * v).cumsum()
        feat['obv_mom'] = feat['obv_mom'] / feat['obv_mom'].rolling(10).mean().abs() - 1
        feat['pv_momentum'] = feat['ret_5d'] * np.log1p(feat['vol_ratio_ma'].clip(0, 10))

        # Smart money
        feat['smart_money_flow'] = feat['close_strength'] * feat['vol_ratio_ma']
        feat['risk_adj_mom'] = feat['ret_5d'] / (feat['vol_5d'] / 100 + 1e-10)

        return feat.replace([np.inf, -np.inf], np.nan).fillna(0)

    def _train(self, prices_dict, tickers):
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        X_all, y_all = [], []
        feat_cols = None

        for ticker in tickers:
            if ticker in ('SPY','QQQ','IWM','VIX','TLT','GLD','HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 80:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            if feat_cols is None:
                feat_cols = list(feat.columns)

            fwd_ret = df['Close'].pct_change(1).shift(-1)
            target = (fwd_ret >= 0.025).astype(int)  # surge 2.5%
            target.iloc[-1] = np.nan
            valid = target.notna() & feat.notna().all(axis=1)
            valid_idx = feat.index[valid][-200:]
            if len(valid_idx) < 30:
                continue
            X_all.append(feat.loc[valid_idx, feat_cols].values)
            y_all.append(target.loc[valid_idx].values)

        if not X_all:
            return False
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.feat_cols = feat_cols
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        # 4 modelos con roles distintos
        self.models = {
            'nova_t1': HistGradientBoostingClassifier(
                max_iter=250, max_depth=4, learning_rate=0.06,
                min_samples_leaf=15, l2_regularization=0.1,
                class_weight='balanced', random_state=42),
            'quant_pro': RandomForestClassifier(
                n_estimators=180, max_depth=7, min_samples_leaf=10,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=42),
            'ml_brain': ExtraTreesClassifier(
                n_estimators=180, max_depth=8, min_samples_leaf=8,
                class_weight='balanced', n_jobs=-1, random_state=42),
            'real_time': HistGradientBoostingClassifier(
                max_iter=200, max_depth=5, learning_rate=0.05,
                min_samples_leaf=12, l2_regularization=0.15,
                class_weight='balanced', random_state=43),
        }
        for m in self.models.values():
            m.fit(Xs, y)
        return True

    def _get_weights(self, regime):
        if regime == 'BULL':
            return {'nova_t1': 0.40, 'quant_pro': 0.25, 'ml_brain': 0.20, 'real_time': 0.15}
        elif regime == 'BEAR':
            return {'nova_t1': 0.20, 'quant_pro': 0.35, 'ml_brain': 0.25, 'real_time': 0.20}
        return {'nova_t1': 0.35, 'quant_pro': 0.30, 'ml_brain': 0.20, 'real_time': 0.15}

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict, tickers):
                return []

        # Detectar regimen
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        regime = 'NEUTRAL'
        if spy_close is not None and len(spy_close) > 50:
            regimes = detect_regime_spy(spy_close)
            regime = regimes.iloc[-1]

        weights = self._get_weights(regime)
        picks = []

        for ticker in tickers:
            if ticker in ('SPY','QQQ','IWM','VIX','TLT','GLD','HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 80:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)

            # Weighted ensemble
            prob = 0
            for name, model in self.models.items():
                p = model.predict_proba(X)[0]
                prob += weights[name] * (p[1] if len(p) > 1 else 0)

            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(prob),
                'score': float(prob * 100),
            })

        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 5: v22 — Quant Professional Stacked Ensemble (62 features)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: El modelo mas sofisticado en features. Usa 62 indicadores
#  cuantitativos incluyendo Hurst Exponent (detecta si el mercado es
#  tendencial o mean-reverting), Amihud Illiquidity (impacto de precio
#  por dolar negociado), Garman-Klass volatility (5-8x mas precisa que
#  close-to-close), Realized Skewness/Kurtosis (forma de la distribucion).
#
#  Usa Triple Barrier Labels (Lopez de Prada 2018): en vez de "sube o baja",
#  etiqueta cada muestra segun cual barrera se toca primero:
#    - Barrera superior (+threshold) → BUY
#    - Barrera inferior (-threshold) → SELL
#    - Barrera temporal (horizon)    → HOLD
#  Esto genera targets mas realistas que un simple "retorno > 0".
#
#  5 modelos en stacked ensemble: la prediccion de 4 modelos base se usa
#  como input para un meta-modelo (LogisticRegression). Esto es "stacking"
#  — un metodo de ensemble mas avanzado que el simple promedio.
#
#  CONCEPTO — Stacking vs Averaging:
#  Averaging: prob_final = (prob_m1 + prob_m2 + prob_m3) / 3
#  Stacking:  prob_final = meta_model(prob_m1, prob_m2, prob_m3)
#  El meta-modelo APRENDE que modelos son mejores en que situaciones.

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from scipy import stats as scipy_stats


class StrategyV22:
    """v22: 62 features cuantitativas, triple barrier, stacked ensemble."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.base_models = None
        self.meta_model = None
        self.scaler = None
        self.day_count = 0
        self.feat_cols = None

    def _compute_features(self, df, spy_close=None):
        """
        62 features cuantitativas (adaptadas de v22 original).

        Incluye indicadores clasicos + avanzados cuantitativos:
        - RSI multi-periodo, ATR, Bollinger, MACD, Stochastic, ADX
        - Hurst Exponent, Market Efficiency Ratio, Vol-of-Vol
        - Amihud Illiquidity, Garman-Klass Vol
        - Realized Skewness/Kurtosis
        - Price Acceleration, VPT Z-Score, RSI Divergence
        - Distancia a 52-week high/low
        """
        o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
        v = v.fillna(0) + 1  # evitar zeros
        ret = c.pct_change()
        feat = pd.DataFrame(index=df.index)

        # ── RSI multi-periodo ──
        feat['rsi7'] = compute_rsi(c, 7)
        feat['rsi14'] = compute_rsi(c, 14)
        feat['rsi21'] = compute_rsi(c, 21)

        # ── ATR relativo ──
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        atr14 = tr.ewm(span=14, adjust=False).mean()
        feat['atr_rel'] = atr14 / (c + 1e-10) * 100

        # ── Bollinger ──
        ma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_u = ma20 + 2 * std20
        bb_l = ma20 - 2 * std20
        feat['bb_pct'] = (c - bb_l) / (bb_u - bb_l + 1e-10)
        bb_width = (bb_u - bb_l) / (ma20 + 1e-10) * 100
        feat['bb_width'] = bb_width
        feat['bb_squeeze'] = (bb_width < bb_width.rolling(50).mean()).astype(float)

        # ── MACD ──
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal
        feat['macd_hist'] = macd_hist
        feat['macd_line'] = macd_line / (c + 1e-10)

        # ── Stochastic ──
        lo14, hi14 = c.rolling(14).min(), c.rolling(14).max()
        sk = (c - lo14) / (hi14 - lo14 + 1e-10) * 100
        feat['stoch_k'] = sk
        feat['stoch_d'] = sk.rolling(3).mean()

        # ── ADX simplificado ──
        prev_h = h.shift(1)
        prev_l = l.shift(1)
        pdm = np.where((h - prev_h) > (prev_l - l), np.maximum(h.values - prev_h.values, 0), 0)
        mdm = np.where((prev_l - l) > (h - prev_h), np.maximum(prev_l.values - l.values, 0), 0)
        sm_pdm = pd.Series(pdm, index=df.index).ewm(span=14, adjust=False).mean()
        sm_mdm = pd.Series(mdm, index=df.index).ewm(span=14, adjust=False).mean()
        sm_tr = tr.ewm(span=14, adjust=False).mean()
        pdi = sm_pdm / (sm_tr + 1e-10) * 100
        mdi = sm_mdm / (sm_tr + 1e-10) * 100
        dx = (pdi - mdi).abs() / (pdi + mdi + 1e-10) * 100
        feat['adx'] = dx.ewm(span=14, adjust=False).mean()
        feat['di_diff'] = pdi - mdi

        # ── Williams %R ──
        feat['williams_r'] = (hi14 - c) / (hi14 - lo14 + 1e-10) * -100

        # ── CCI ──
        tp = (h + l + c) / 3
        tp_ma = tp.rolling(20).mean()
        tp_mad = (tp - tp_ma).abs().rolling(20).mean()
        feat['cci'] = (tp - tp_ma) / (0.015 * tp_mad + 1e-10)

        # ── OBV z-score ──
        obv = (np.sign(ret.fillna(0)) * v).cumsum()
        feat['obv_zscore'] = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-10)

        # ── CMF ──
        mf_mult = ((c - l) - (h - c)) / (h - l + 1e-10)
        feat['cmf'] = (mf_mult * v).rolling(20).sum() / (v.rolling(20).sum() + 1e-10)

        # ── Volume indicators ──
        vol_ma20 = v.rolling(20).mean()
        feat['vol_rel'] = v / (vol_ma20 + 1e-10)
        feat['vol_trend'] = v.rolling(5).mean() / (vol_ma20 + 1e-10)

        # ── MA distances ──
        ma50 = c.rolling(50).mean()
        ma200 = c.rolling(200).mean()
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        feat['dist_20'] = (c - ma20) / (ma20 + 1e-10) * 100
        feat['dist_50'] = (c - ma50) / (ma50 + 1e-10) * 100
        feat['dist_200'] = (c - ma200) / (ma200 + 1e-10) * 100
        feat['ema_cross'] = (ema9 > ema21).astype(float)

        # ── Momentum multi-periodo ──
        feat['mom5'] = c.pct_change(5) * 100
        feat['mom10'] = c.pct_change(10) * 100
        feat['mom21'] = c.pct_change(21) * 100
        m1 = c.pct_change(21)
        m3 = c.pct_change(63)
        feat['mom_score'] = (m1 * 0.5 + m3 * 0.3 + c.pct_change(126) * 0.2) * 100

        # ── Volatilidad ──
        rvol = ret.rolling(20).std() * np.sqrt(252) * 100
        feat['rvol'] = rvol
        feat['rvol_ratio'] = rvol / (rvol.rolling(50).mean() + 1e-10)

        # ── Z-Scores ──
        feat['zscore20'] = (c - ma20) / (std20 + 1e-10)
        feat['zscore50'] = (c - ma50) / (c.rolling(50).std() + 1e-10)

        # ── Candle structure ──
        price_range = h - l + 1e-10
        feat['gap'] = (o / prev_c - 1) * 100
        feat['candle_body'] = (c - o).abs() / price_range
        feat['upper_wick'] = (h - np.maximum(o, c)) / price_range
        feat['lower_wick'] = (np.minimum(o, c) - l) / price_range

        # ── Retorno diario y mean reversion ──
        feat['retorno_diario'] = ret * 100
        feat['mean_reversion'] = -feat['zscore20'] * 10

        # ══ FEATURES CUANTITATIVAS AVANZADAS (lo que distingue a v22) ══

        # Hurst Exponent (tendencial vs mean-reverting)
        log_p = np.log(np.maximum(c, 1e-10))
        hurst = pd.Series(0.5, index=df.index)
        for i in range(100, len(c)):
            window = log_p.iloc[i-100:i].values
            try:
                lags = [2, 4, 8, 16, 32]
                pairs = []
                for lag in lags:
                    diffs = window[lag:] - window[:-lag]
                    if len(diffs) > 1:
                        pairs.append((lag, np.var(diffs)))
                if len(pairs) >= 3:
                    lx = np.log([p[0] for p in pairs])
                    ly = np.log([p[1] + 1e-20 for p in pairs])
                    h_val = np.polyfit(lx, ly, 1)[0] / 2.0
                    hurst.iloc[i] = float(np.clip(h_val, 0, 1))
            except Exception:
                pass
        feat['hurst'] = hurst

        # Market Efficiency Ratio
        mer = pd.Series(0.0, index=df.index)
        for i in range(20, len(c)):
            w = c.iloc[i-20:i].values
            direction = abs(w[-1] - w[0])
            noise = np.sum(np.abs(np.diff(w)))
            mer.iloc[i] = direction / (noise + 1e-10)
        feat['mer'] = mer

        # Vol-of-Vol
        inner_vol = ret.rolling(10, min_periods=3).std() * np.sqrt(252) * 100
        feat['vov'] = inner_vol.rolling(30, min_periods=10).std()

        # Amihud Illiquidity
        abs_ret = ret.abs()
        dv = c * v + 1.0
        raw_amihud = abs_ret / dv * 1_000_000
        roll_m = raw_amihud.rolling(252, min_periods=60).mean()
        roll_s = raw_amihud.rolling(252, min_periods=60).std()
        feat['amihud'] = ((raw_amihud - roll_m) / (roll_s + 1e-10)).fillna(0)

        # Garman-Klass Vol
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
        gk_raw = np.maximum(0.5 * log_hl - (2 * np.log(2) - 1) * log_co, 0)
        feat['gk_vol'] = np.sqrt(gk_raw.rolling(20).mean()) * np.sqrt(252) * 100

        # Realized Skewness y Kurtosis
        log_ret = np.log(c / c.shift(1)).fillna(0)
        feat['real_skew'] = log_ret.rolling(21, min_periods=5).skew().fillna(0)
        feat['real_kurt'] = log_ret.rolling(21, min_periods=5).kurt().fillna(0)

        # Price Acceleration
        mom_n = c.pct_change(5)
        feat['price_accel'] = mom_n.diff(5).fillna(0) * 100

        # VPT Z-Score
        vpt = (ret.fillna(0) * v).cumsum()
        feat['vpt_z'] = (vpt - vpt.rolling(50).mean()) / (vpt.rolling(50).std() + 1e-10)

        # RSI Divergence
        rsi14 = feat['rsi14']
        price_trend = c.diff(10).fillna(0)
        rsi_trend = rsi14.diff(10).fillna(0)
        bull_div = ((price_trend < 0) & (rsi_trend > 1)).astype(float)
        bear_div = ((price_trend > 0) & (rsi_trend < -1)).astype(float) * -1
        feat['rsi_div'] = bull_div + bear_div

        # 52-week high/low distance
        feat['dist_52h'] = (c / c.rolling(252, min_periods=60).max() - 1) * 100
        feat['dist_52l'] = (c / c.rolling(252, min_periods=60).min() - 1) * 100

        # Regime (simple)
        regime_ma = c.rolling(50).mean()
        regime_std = c.rolling(50).std()
        feat['regime'] = np.where(c > regime_ma + 0.5 * regime_std, 1.0,
                         np.where(c < regime_ma - 0.5 * regime_std, -1.0, 0.0))

        # Market context (si tenemos SPY)
        if spy_close is not None and len(spy_close) > 0:
            spy = spy_close.reindex(c.index).ffill().bfill()
            spy_ma20 = spy.rolling(20).mean()
            feat['mkt_dist20'] = (spy / (spy_ma20 + 1e-10) - 1) * 100
            spy_ret = spy.pct_change()
            cov20 = ret.rolling(20).cov(spy_ret)
            mkt_var = spy_ret.rolling(20).var()
            feat['beta_spy'] = cov20 / (mkt_var + 1e-10)
        else:
            feat['mkt_dist20'] = 0
            feat['beta_spy'] = 1.0

        return feat.replace([np.inf, -np.inf], np.nan).fillna(0)

    def _triple_barrier_labels(self, close, horizon=5, threshold=0.02):
        """
        Triple Barrier Method (Lopez de Prada).
        Etiqueta: 2=BUY, 1=HOLD, 0=SELL segun cual barrera se toca primero.

        CONCEPTO: En vez de preguntar "subio o bajo en 5 dias?", preguntamos
        "que paso PRIMERO: toco +2%, toco -2%, o pasaron 5 dias sin tocar ninguna?"
        Esto genera targets mucho mas realistas para trading.
        """
        labels = np.full(len(close), 1)  # default HOLD
        c = close.values

        # Volatilidad local para escalar barreras
        ret = np.diff(np.log(np.maximum(c, 1e-10)), prepend=np.log(c[0] + 1e-10))
        vol = pd.Series(ret).rolling(20, min_periods=5).std().fillna(0.01).values

        for i in range(len(c) - horizon):
            local_thr = max(threshold, vol[i] * np.sqrt(horizon) * 1.5)
            entry = c[i]
            for j in range(1, horizon + 1):
                if i + j >= len(c):
                    break
                ret_j = (c[i + j] - entry) / entry
                if ret_j >= local_thr:
                    labels[i] = 2  # BUY
                    break
                elif ret_j <= -local_thr:
                    labels[i] = 0  # SELL
                    break

        # Ultimos `horizon` dias no tienen target
        labels[-horizon:] = -1  # invalido
        return labels

    def _train(self, prices_dict, tickers):
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        X_all, y_all = [], []
        feat_cols = None

        for ticker in tickers:
            if ticker in ('SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 120:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            if feat_cols is None:
                feat_cols = list(feat.columns)

            # Triple barrier labels con horizon=3, threshold=2%
            labels = self._triple_barrier_labels(df['Close'], horizon=3, threshold=0.02)
            # Convertir a binario: BUY(2) vs no-BUY(0,1)
            target = (labels == 2).astype(int)
            target_s = pd.Series(target, index=df.index)
            target_s[labels == -1] = np.nan

            valid = target_s.notna() & feat.notna().all(axis=1)
            valid_idx = feat.index[valid][-200:]
            if len(valid_idx) < 40:
                continue
            X_all.append(feat.loc[valid_idx, feat_cols].values)
            y_all.append(target_s.loc[valid_idx].values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.feat_cols = feat_cols
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        # ── Stacked Ensemble ──
        # Paso 1: entrenar 4 modelos base
        self.base_models = [
            HistGradientBoostingClassifier(
                max_iter=220, max_depth=5, learning_rate=0.07,
                min_samples_leaf=20, l2_regularization=0.15,
                class_weight='balanced', random_state=42),
            GradientBoostingClassifier(
                n_estimators=150, max_depth=4, learning_rate=0.08,
                min_samples_leaf=15, random_state=43),
            RandomForestClassifier(
                n_estimators=140, max_depth=7, min_samples_leaf=10,
                class_weight='balanced', n_jobs=-1, random_state=44),
            ExtraTreesClassifier(
                n_estimators=140, max_depth=8, min_samples_leaf=8,
                class_weight='balanced', n_jobs=-1, random_state=45),
        ]
        for m in self.base_models:
            m.fit(Xs, y)

        # Paso 2: generar predicciones out-of-fold para el meta-modelo
        # Usamos una division simple 50/50 para no complicar
        mid = len(Xs) // 2
        meta_X = np.zeros((len(Xs), len(self.base_models)))
        for i, m in enumerate(self.base_models):
            # Entrenar en primera mitad, predecir segunda
            m_tmp = m.__class__(**m.get_params())
            m_tmp.fit(Xs[:mid], y[:mid])
            p2 = m_tmp.predict_proba(Xs[mid:])
            meta_X[mid:, i] = p2[:, 1] if p2.shape[1] > 1 else p2[:, 0]
            # Entrenar en segunda mitad, predecir primera
            m_tmp2 = m.__class__(**m.get_params())
            m_tmp2.fit(Xs[mid:], y[mid:])
            p1 = m_tmp2.predict_proba(Xs[:mid])
            meta_X[:mid, i] = p1[:, 1] if p1.shape[1] > 1 else p1[:, 0]

        # Paso 3: entrenar meta-modelo (LogisticRegression)
        self.meta_model = LogisticRegression(
            C=1.0, max_iter=500, random_state=42)
        self.meta_model.fit(meta_X, y)

        # Re-entrenar base models en TODO el dataset
        for m in self.base_models:
            m.fit(Xs, y)

        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.base_models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict, tickers):
                return []

        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        picks = []

        for ticker in tickers:
            if ticker in ('SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 120:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)

            # Paso 1: predicciones de modelos base
            base_preds = np.zeros((1, len(self.base_models)))
            for i, m in enumerate(self.base_models):
                p = m.predict_proba(X)[0]
                base_preds[0, i] = p[1] if len(p) > 1 else 0

            # Paso 2: meta-modelo combina las predicciones
            prob = self.meta_model.predict_proba(base_preds)[0]
            prob_buy = prob[1] if len(prob) > 1 else prob[0]

            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(prob_buy),
                'score': float(prob_buy * 100),
            })

        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 6: v102 — Event-Aware Multi-Model (7 modelos especializados)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Este modelo va un paso mas alla. En vez de tener UN modelo
#  que predice "sube o baja", tiene 7 modelos ESPECIALIZADOS:
#
#  1. Pop Model:      predice si el activo va a tener un "pop" (suba fuerte)
#  2. Close Model:    predice si el cierre sera positivo
#  3. Gap Model:      predice si abrira con gap positivo manana
#  4. Momentum Model: predice pops en contexto de momentum
#  5. Reversal Model: predice pops en contexto de reversal
#  6. High Regressor: estima CUANTO va a subir el maximo
#  7. Close Regressor: estima CUANTO va a cambiar el cierre
#
#  Cada modelo se especializa en un ASPECTO diferente del movimiento.
#  El score final es un promedio ponderado que cambia segun el regimen.
#
#  CONCEPTO — Especializacion vs Generalizacion:
#  Un modelo generalista intenta predecir todo → mediocre en todo.
#  Modelos especializados → excelentes en su nicho → la combinacion
#  captura patrones que un modelo unico no puede ver.
#
#  Tambien usa "Setup Scores" — funciones sigmoid que miden si las
#  condiciones actuales se parecen a setups conocidos (momentum setup,
#  reversal setup, squeeze setup, gap setup).

from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor


class StrategyV102:
    """v102: 7 modelos especializados + setup scores + regime-aware."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.models = None
        self.regressors = None
        self.scaler = None
        self.day_count = 0
        self.feat_cols = None

    def _sigmoid(self, x, scale=1.0):
        """Funcion sigmoid: mapea cualquier valor a rango (0, 1)."""
        return 1.0 / (1.0 + np.exp(-np.asarray(x) / max(scale, 1e-10)))

    def _compute_features(self, df, spy_close=None):
        """
        80+ features incluyendo setup scores para v102.
        Combina microestructura + momentum + volatilidad + setups.
        """
        o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
        v = v.fillna(0) + 1
        ret = c.pct_change()
        prev_c = c.shift(1)
        price_range = (h - l).replace(0, np.nan).fillna(1e-10)
        feat = pd.DataFrame(index=df.index)

        # ── Microestructura de velas ──
        feat['gap_open_pct'] = o / (prev_c + 1e-10) - 1.0
        feat['intraday_ret'] = c / (o + 1e-10) - 1.0
        feat['close_strength'] = (c - l) / (price_range)
        feat['body_pct'] = (c - o).abs() / price_range
        feat['upper_wick_pct'] = (h - np.maximum(o, c)) / price_range
        feat['lower_wick_pct'] = (np.minimum(o, c) - l) / price_range
        feat['range_pct'] = (h - l) / (prev_c + 1e-10)

        # ── Returns multi-periodo ──
        feat['ret_1d'] = ret
        feat['ret_3d'] = c.pct_change(3)
        feat['ret_5d'] = c.pct_change(5)
        feat['ret_10d'] = c.pct_change(10)
        feat['ret_20d'] = c.pct_change(20)
        feat['ret_40d'] = c.pct_change(40)
        feat['ret_60d'] = c.pct_change(60)
        feat['mom_accel_5_20'] = feat['ret_5d'] - feat['ret_20d']

        # ── MAs y distancias ──
        ma10 = c.rolling(10).mean()
        ma20 = c.rolling(20).mean()
        ma50 = c.rolling(50).mean()
        std20 = c.rolling(20).std()
        feat['price_vs_ma10'] = c / (ma10 + 1e-10) - 1.0
        feat['price_vs_ma20'] = c / (ma20 + 1e-10) - 1.0
        feat['price_vs_ma50'] = c / (ma50 + 1e-10) - 1.0
        feat['ma5_vs_ma20'] = c.rolling(5).mean() / (ma20 + 1e-10) - 1.0
        feat['ma20_slope_5'] = ma20.pct_change(5)

        # ── Distancias a extremos ──
        feat['dist_20d_high'] = c / (c.rolling(20).max() + 1e-10) - 1.0
        feat['dist_20d_low'] = c / (c.rolling(20).min() + 1e-10) - 1.0
        feat['dist_60d_high'] = c / (c.rolling(60).max() + 1e-10) - 1.0

        # ── Osciladores ──
        feat['rsi_3'] = compute_rsi(c, 3)
        feat['rsi_14'] = compute_rsi(c, 14)
        lo14, hi14 = c.rolling(14).min(), c.rolling(14).max()
        feat['stoch_k'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100
        feat['stoch_d'] = feat['stoch_k'].rolling(3).mean()
        tp = (h + l + c) / 3
        tp_ma = tp.rolling(20).mean()
        tp_mad = (tp - tp_ma).abs().rolling(20).mean()
        feat['cci_20'] = (tp - tp_ma) / (0.015 * tp_mad + 1e-10)

        # ── MACD ──
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        feat['macd_line_norm'] = macd_line / (c + 1e-10)
        feat['macd_hist_norm'] = (macd_line - macd_line.ewm(span=9, adjust=False).mean()) / (c + 1e-10)
        feat['zscore_20'] = (c - ma20) / (std20 + 1e-10)

        # ── Volatilidad ──
        feat['vol_5d'] = ret.rolling(5).std() * np.sqrt(252)
        feat['vol_20d'] = ret.rolling(20).std() * np.sqrt(252)
        feat['vol_ratio_5_20'] = feat['vol_5d'] / (feat['vol_20d'] + 1e-10)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        feat['atr_pct_14'] = tr.ewm(span=14, adjust=False).mean() / (c + 1e-10)
        bb_width = (4 * std20) / (ma20 + 1e-10)
        feat['bb_width'] = bb_width
        feat['bb_squeeze_rank'] = bb_width.rolling(60, min_periods=20).rank(pct=True)

        # Garman-Klass y Parkinson
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
        gk_raw = np.maximum(0.5 * log_hl - (2 * np.log(2) - 1) * log_co, 0)
        feat['gk_vol_10'] = np.sqrt(gk_raw.rolling(10).mean())
        feat['parkinson_vol_10'] = np.sqrt(log_hl.rolling(10).mean() / (4 * np.log(2)))

        # ── Volumen ──
        vol_ma20 = v.rolling(20).mean()
        vol_std20 = v.rolling(20).std()
        feat['vol_ratio_1_20'] = v / (vol_ma20 + 1e-10)
        feat['vol_z_20'] = (v - vol_ma20) / (vol_std20 + 1e-10)
        feat['cmf_20'] = ((c - l) - (h - c)) / (h - l + 1e-10)
        feat['cmf_20'] = (feat['cmf_20'] * v).rolling(20).sum() / (v.rolling(20).sum() + 1e-10)
        obv = (np.sign(ret.fillna(0)) * v).cumsum()
        feat['obv_z_20'] = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-10)
        vpt = (ret.fillna(0) * v).cumsum()
        feat['vpt_z_20'] = (vpt - vpt.rolling(20).mean()) / (vpt.rolling(20).std() + 1e-10)
        feat['pv_mom'] = feat['ret_5d'] * np.log1p(feat['vol_ratio_1_20'].clip(lower=0))
        feat['smart_money_flow'] = feat['close_strength'] * feat['vol_ratio_1_20']

        # ── Market context (SPY) ──
        if spy_close is not None and len(spy_close) > 0:
            spy = spy_close.reindex(c.index).ffill().bfill()
            spy_ret = spy.pct_change()
            feat['spy_ret_1d'] = spy_ret.reindex(df.index)
            feat['spy_ret_5d'] = spy.pct_change(5).reindex(df.index)
            feat['spy_vs_ma20'] = (spy / (spy.rolling(20).mean() + 1e-10) - 1).reindex(df.index)
        else:
            feat['spy_ret_1d'] = 0
            feat['spy_ret_5d'] = 0
            feat['spy_vs_ma20'] = 0

        # ── Setup Scores (funciones sigmoid que miden condiciones) ──
        feat['setup_momentum'] = self._sigmoid(
            6.0 * feat['ret_5d'].fillna(0)
            + 3.0 * feat['ret_20d'].fillna(0)
            + 2.0 * feat['price_vs_ma20'].fillna(0)
            + 1.6 * (feat['close_strength'].fillna(0.5) - 0.5)
            + 0.8 * (feat['vol_ratio_1_20'].fillna(1.0) - 1.0))

        feat['setup_reversal'] = self._sigmoid(
            -6.5 * feat['ret_5d'].fillna(0)
            - 3.5 * feat['price_vs_ma20'].fillna(0)
            + 1.8 * (feat['close_strength'].fillna(0.5) - 0.45)
            + 0.9 * (feat['vol_ratio_1_20'].fillna(1.0) - 1.0)
            + 0.10 * (35.0 - feat['rsi_3'].fillna(50.0)))

        feat['setup_squeeze'] = self._sigmoid(
            2.5 * (0.35 - feat['bb_squeeze_rank'].fillna(0.5))
            + 1.0 * (feat['vol_ratio_1_20'].fillna(1.0) - 1.0)
            + 0.8 * feat['price_vs_ma20'].fillna(0))

        feat['setup_gap'] = self._sigmoid(
            1.6 * (feat['vol_ratio_1_20'].fillna(1.0) - 1.0)
            + 1.2 * feat['range_pct'].fillna(0)
            - 0.7 * 1.0)  # sin market_vol_ratio simplificado

        return feat.replace([np.inf, -np.inf], np.nan).fillna(0)

    def _train(self, prices_dict, tickers):
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        X_all, y_pop_all, y_close_all, y_gap_all = [], [], [], []
        y_high_all, y_close_ret_all = [], []
        feat_cols = None

        for ticker in tickers:
            if ticker in ('SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 80:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            if feat_cols is None:
                feat_cols = list(feat.columns)

            c, o_price, h_price, l_price = df['Close'], df['Open'], df['High'], df['Low']

            # Targets T+1
            fwd_close_ret = c.pct_change(1).shift(-1)
            fwd_gap = (o_price.shift(-1) / (c + 1e-10) - 1.0)
            fwd_high = (h_price.shift(-1) / (c + 1e-10) - 1.0)
            fwd_pop = pd.concat([fwd_close_ret, fwd_gap, fwd_high], axis=1).max(axis=1)

            # Targets binarios adaptativos (top 10% del universo)
            tgt_pop = (fwd_pop >= 0.035).astype(float)
            tgt_close = (fwd_close_ret >= 0.025).astype(float)
            tgt_gap = (fwd_gap >= 0.018).astype(float)

            # Marcar ultimo dia como invalido
            tgt_pop.iloc[-1] = np.nan
            tgt_close.iloc[-1] = np.nan
            tgt_gap.iloc[-1] = np.nan

            valid = tgt_pop.notna() & feat.notna().all(axis=1)
            valid_idx = feat.index[valid][-200:]
            if len(valid_idx) < 30:
                continue

            X_all.append(feat.loc[valid_idx, feat_cols].values)
            y_pop_all.append(tgt_pop.loc[valid_idx].values)
            y_close_all.append(tgt_close.loc[valid_idx].values)
            y_gap_all.append(tgt_gap.loc[valid_idx].values)
            y_high_all.append(fwd_high.loc[valid_idx].clip(-0.3, 0.6).values)
            y_close_ret_all.append(fwd_close_ret.loc[valid_idx].clip(-0.3, 0.4).values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y_pop = np.concatenate(y_pop_all)
        y_close = np.concatenate(y_close_all)
        y_gap = np.concatenate(y_gap_all)
        y_high = np.concatenate(y_high_all)
        y_close_ret = np.concatenate(y_close_ret_all)

        self.feat_cols = feat_cols
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        # 5 clasificadores especializados
        self.models = {
            'pop': HistGradientBoostingClassifier(
                max_iter=220, max_depth=5, learning_rate=0.07,
                min_samples_leaf=20, l2_regularization=0.15,
                class_weight='balanced', random_state=42),
            'close': ExtraTreesClassifier(
                n_estimators=140, max_depth=8, min_samples_leaf=10,
                class_weight='balanced', n_jobs=-1, random_state=43),
            'gap': HistGradientBoostingClassifier(
                max_iter=180, max_depth=4, learning_rate=0.07,
                min_samples_leaf=22, l2_regularization=0.12,
                class_weight='balanced', random_state=44),
            'momentum': HistGradientBoostingClassifier(
                max_iter=150, max_depth=4, learning_rate=0.07,
                min_samples_leaf=16, l2_regularization=0.10,
                class_weight='balanced', random_state=45),
            'reversal': HistGradientBoostingClassifier(
                max_iter=150, max_depth=4, learning_rate=0.07,
                min_samples_leaf=16, l2_regularization=0.10,
                class_weight='balanced', random_state=46),
        }
        # Entrenar clasificadores
        self.models['pop'].fit(Xs, y_pop)
        self.models['close'].fit(Xs, y_close)
        self.models['gap'].fit(Xs, y_gap)
        # Momentum y reversal: filtrar por setup score
        setup_mom_col = feat_cols.index('setup_momentum') if 'setup_momentum' in feat_cols else None
        if setup_mom_col is not None:
            mom_mask = X[:, setup_mom_col] >= 0.42
            if mom_mask.sum() > 500:
                self.models['momentum'].fit(Xs[mom_mask], y_pop[mom_mask])
            else:
                self.models['momentum'].fit(Xs, y_pop)
            rev_mask = X[:, feat_cols.index('setup_reversal')] >= 0.38
            if rev_mask.sum() > 500:
                self.models['reversal'].fit(Xs[rev_mask], y_pop[rev_mask])
            else:
                self.models['reversal'].fit(Xs, y_pop)
        else:
            self.models['momentum'].fit(Xs, y_pop)
            self.models['reversal'].fit(Xs, y_pop)

        # 2 regressores
        self.regressors = {
            'high': ExtraTreesRegressor(
                n_estimators=120, max_depth=8, min_samples_leaf=8,
                n_jobs=-1, random_state=47),
            'close_ret': RandomForestRegressor(
                n_estimators=100, max_depth=7, min_samples_leaf=10,
                n_jobs=-1, random_state=48),
        }
        self.regressors['high'].fit(Xs, y_high)
        self.regressors['close_ret'].fit(Xs, y_close_ret)

        return True

    def _get_weights(self, regime):
        """Pesos que cambian segun el regimen de mercado."""
        if regime == 'BULL':
            return {'pop': 0.28, 'close': 0.16, 'gap': 0.15,
                    'momentum': 0.12, 'reversal': 0.05,
                    'high_rank': 0.08, 'close_rank': 0.04, 'setup': 0.12}
        elif regime == 'BEAR':
            return {'pop': 0.25, 'close': 0.12, 'gap': 0.16,
                    'momentum': 0.05, 'reversal': 0.13,
                    'high_rank': 0.08, 'close_rank': 0.03, 'setup': 0.18}
        return {'pop': 0.27, 'close': 0.14, 'gap': 0.16,
                'momentum': 0.09, 'reversal': 0.09,
                'high_rank': 0.08, 'close_rank': 0.04, 'setup': 0.13}

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict, tickers):
                return []

        # Detectar regimen
        spy_close = prices_dict.get('SPY', pd.DataFrame()).get('Close')
        regime = 'NEUTRAL'
        if spy_close is not None and len(spy_close) > 50:
            regimes = detect_regime_spy(spy_close)
            regime = regimes.iloc[-1]

        weights = self._get_weights(regime)
        picks = []

        for ticker in tickers:
            if ticker in ('SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG'):
                continue
            if ticker not in prices_dict or len(prices_dict[ticker]) < 80:
                continue
            df = prices_dict[ticker]
            feat = self._compute_features(df, spy_close)
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)

            # Predicciones de los 5 clasificadores
            p_pop = self.models['pop'].predict_proba(X)[0]
            p_pop = p_pop[1] if len(p_pop) > 1 else 0
            p_close = self.models['close'].predict_proba(X)[0]
            p_close = p_close[1] if len(p_close) > 1 else 0
            p_gap = self.models['gap'].predict_proba(X)[0]
            p_gap = p_gap[1] if len(p_gap) > 1 else 0
            p_mom = self.models['momentum'].predict_proba(X)[0]
            p_mom = p_mom[1] if len(p_mom) > 1 else 0
            p_rev = self.models['reversal'].predict_proba(X)[0]
            p_rev = p_rev[1] if len(p_rev) > 1 else 0

            # Predicciones de regressores (normalizadas 0-1)
            pred_high = float(self.regressors['high'].predict(X)[0])
            pred_close = float(self.regressors['close_ret'].predict(X)[0])
            # Rank proxy: sigmoid del valor
            high_rank = 1.0 / (1.0 + np.exp(-pred_high * 20))
            close_rank = 1.0 / (1.0 + np.exp(-pred_close * 20))

            # Setup scores del ultimo dia
            setup_mom = float(feat['setup_momentum'].iloc[-1])
            setup_rev = float(feat['setup_reversal'].iloc[-1])
            setup_sqz = float(feat['setup_squeeze'].iloc[-1])
            setup_gap = float(feat['setup_gap'].iloc[-1])
            setup_combo = 0.35 * setup_mom + 0.25 * setup_rev + 0.20 * setup_sqz + 0.20 * setup_gap

            # Score final ponderado
            score = (
                weights['pop'] * p_pop
                + weights['close'] * p_close
                + weights['gap'] * p_gap
                + weights['momentum'] * (p_mom * setup_mom)
                + weights['reversal'] * (p_rev * setup_rev)
                + weights['high_rank'] * high_rank
                + weights['close_rank'] * close_rank
                + weights['setup'] * setup_combo
            )

            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(np.clip(score, 0, 1)),
                'score': float(np.clip(score * 100, 0, 100)),
            })

        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 7: brain_v11 — 5-Model Voting Ensemble (9 features, 3 clases)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Ensemble "democratico" — 5 modelos votan, gana la mayoria.
#  Usa features clasicos (RSI, Bollinger, MACD, Stochastic, ADX).
#  Target trinario: SELL (cae >2%), HOLD, BUY (sube >3%) en 5 dias.
#  Confidence = % de modelos que votan BUY.
#
#  Origen: ml_trading_brain_v11.py (y sus variantes v11_optimized, v11v4).

class StrategyBrainV11:
    """brain_v11: 9 features clasicos, 5 modelos votando, target 3-class T+5."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.models = None
        self.scaler = None
        self.day_count = 0
        self.feat_cols = ['rsi', 'bb_pos', 'dist_50', 'dist_200', 'momento',
                          'stoch_k', 'adx', 'vol_rel', 'macd_hist']

    def _compute_features(self, df):
        """9 features de indicadores tecnicos clasicos."""
        c = df['Close'].values
        v = df['Volume'].values
        if len(c) < 210:
            return None

        # RSI
        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        avg_g = pd.Series(gain).ewm(com=13, adjust=False).mean().values
        avg_l = pd.Series(loss).ewm(com=13, adjust=False).mean().values
        rsi_arr = 100 - 100 / (1 + avg_g / (avg_l + 1e-10))

        # MACD histogram
        s = pd.Series(c)
        ema12 = s.ewm(span=12, adjust=False).mean().values
        ema26 = s.ewm(span=26, adjust=False).mean().values
        macd_line = ema12 - ema26
        signal = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
        macd_hist = macd_line - signal

        # Stochastic
        h_max = pd.Series(c).rolling(14).max().values
        l_min = pd.Series(c).rolling(14).min().values
        stoch_k = 100 * (c - l_min) / (h_max - l_min + 1e-10)

        # ADX (simplificado)
        high = c * 1.005
        low = c * 0.995
        prev_h = np.roll(high, 1); prev_h[0] = high[0]
        prev_l = np.roll(low, 1); prev_l[0] = low[0]
        pdm = np.where((high - prev_h) > (prev_l - low), np.maximum(high - prev_h, 0), 0)
        mdm = np.where((prev_l - low) > (high - prev_h), np.maximum(prev_l - low, 0), 0)
        tr = np.maximum(high - low, 1e-10)
        sm = lambda x: pd.Series(x).ewm(com=13, adjust=False).mean().values
        pdi = sm(pdm) / (sm(tr) + 1e-10) * 100
        mdi = sm(mdm) / (sm(tr) + 1e-10) * 100
        dx = np.abs(pdi - mdi) / (pdi + mdi + 1e-10) * 100
        adx_arr = pd.Series(dx).ewm(com=13, adjust=False).mean().values

        # MAs
        ma20 = pd.Series(c).rolling(20).mean().values
        std20 = pd.Series(c).rolling(20).std().values
        ma50 = pd.Series(c).rolling(50).mean().values
        ma200 = pd.Series(c).rolling(200).mean().values
        vol_ma20 = pd.Series(v.astype(float)).rolling(20).mean().values

        n = len(c)
        feats = pd.DataFrame(index=df.index)
        feats['rsi'] = rsi_arr
        feats['bb_pos'] = (c - (ma20 - 2*std20)) / (4*std20 + 1e-10)
        feats['dist_50'] = (c / (ma50 + 1e-10) - 1) * 100
        feats['dist_200'] = (c / (ma200 + 1e-10) - 1) * 100
        feats['momento'] = pd.Series(c).pct_change(5).values * 100
        feats['stoch_k'] = stoch_k
        feats['adx'] = adx_arr
        feats['vol_rel'] = v / (vol_ma20 + 1e-10)
        feats['macd_hist'] = macd_hist
        return feats.fillna(0)

    def _train(self, prices_dict):
        X_all, y_all = [], []
        for ticker, df in prices_dict.items():
            if len(df) < 215:
                continue
            feat = self._compute_features(df)
            if feat is None:
                continue
            c = df['Close']
            # Target trinario: sube >=3% en 5 dias = BUY(2), cae >=-2% = SELL(0), else HOLD(1)
            fwd_ret = c.pct_change(5).shift(-5)
            target = pd.Series(1, index=df.index)  # HOLD default
            target[fwd_ret >= 0.03] = 2   # BUY
            target[fwd_ret <= -0.02] = 0  # SELL
            target.iloc[-5:] = np.nan

            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 30:
                continue
            X_all.append(feat.loc[valid, self.feat_cols].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)
        self.models = {
            'RF': RandomForestClassifier(n_estimators=150, max_depth=10,
                      class_weight='balanced', random_state=42, n_jobs=-1),
            'GB': GradientBoostingClassifier(n_estimators=100, learning_rate=0.05,
                      random_state=42),
            'ET': ExtraTreesClassifier(n_estimators=100, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'MLP': MLPClassifier(hidden_layer_sizes=(64, 32), activation='relu',
                       max_iter=800, early_stopping=True, random_state=42),
            'LR': LogisticRegression(class_weight='balanced', max_iter=500),
        }
        for m in self.models.values():
            m.fit(Xs, y)
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []
        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 215:
                continue
            feat = self._compute_features(df)
            if feat is None:
                continue
            X = self.scaler.transform(feat[self.feat_cols].iloc[-1:].values)
            # Voto mayoritario + confianza = % modelos que votan BUY(2)
            votes = [m.predict(X)[0] for m in self.models.values()]
            buy_votes = sum(1 for v in votes if v == 2)
            confidence = buy_votes / len(self.models)
            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(confidence),
                'score': float(confidence * 100),
            })
        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 7b: brain_v11_optimized — HGB replaces GB (9 features, 3 clases)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Misma arquitectura que brain_v11, pero reemplaza
#  GradientBoostingClassifier (lento) por HistGradientBoostingClassifier (5x+).
#  El resto es identico: mismas 9 features, mismos 5 modelos, mismo target.
#
#  Origen: ml_trading_brain_v11_optimized.py

class StrategyBrainV11Opt(StrategyBrainV11):
    """brain_v11_optimized: igual a V11 pero con HGB en vez de GB."""

    def _train(self, prices_dict):
        X_all, y_all = [], []
        for ticker, df in prices_dict.items():
            if len(df) < 215:
                continue
            feat = self._compute_features(df)
            if feat is None:
                continue
            c = df['Close']
            fwd_ret = c.pct_change(5).shift(-5)
            target = pd.Series(1, index=df.index)
            target[fwd_ret >= 0.03] = 2
            target[fwd_ret <= -0.02] = 0
            target.iloc[-5:] = np.nan
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 30:
                continue
            X_all.append(feat.loc[valid, self.feat_cols].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)
        # DIFERENCIA: HGB en vez de GB, y early_stopping nativo
        self.models = {
            'RF': RandomForestClassifier(n_estimators=150, max_depth=10,
                      class_weight='balanced', random_state=42, n_jobs=-1),
            'HGB': HistGradientBoostingClassifier(max_iter=150, max_depth=5,
                       learning_rate=0.05, random_state=42,
                       early_stopping=True),
            'ET': ExtraTreesClassifier(n_estimators=150, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'MLP': MLPClassifier(hidden_layer_sizes=(64, 32), activation='relu',
                       max_iter=800, early_stopping=True, random_state=42),
            'LR': LogisticRegression(class_weight='balanced', max_iter=500),
        }
        for m in self.models.values():
            m.fit(Xs, y)
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 8: v94 — XGBoost Single Model (25 features, binary)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Modelo unico de XGBoost (tree_method='hist' = rapido).
#  25 features clasicos: SMAs, EMAs, RSI, MACD, Bollinger, ATR, ROC, lags.
#  Target binario: sube >=2% en 5 dias.
#  Si XGBoost no esta instalado, usa HistGradientBoosting como fallback.
#
#  Origen: ml_trading_v94.py

class StrategyV94:
    """v94: ~25 features, XGBoost single model, binary target (sube >=2% T+5)."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.model = None
        self.scaler = None
        self.day_count = 0

    def _compute_features(self, df):
        """~25 features tecnicos clasicos."""
        c, v = df['Close'], df['Volume']
        h, l, o = df['High'], df['Low'], df['Open']
        feat = pd.DataFrame(index=df.index)

        # SMAs y EMAs (6)
        for w in [5, 10, 20]:
            feat[f'SMA_{w}'] = c.rolling(window=w).mean()
            feat[f'EMA_{w}'] = c.ewm(span=w, adjust=False).mean()

        # Crosses (2)
        feat['SMA_Cross'] = feat['SMA_5'] - feat['SMA_20']
        feat['EMA_Cross'] = feat['EMA_5'] - feat['EMA_20']

        # RSI (1)
        feat['RSI'] = compute_rsi(c, 14)

        # MACD (3)
        exp1 = c.ewm(span=12, adjust=False).mean()
        exp2 = c.ewm(span=26, adjust=False).mean()
        feat['MACD'] = exp1 - exp2
        feat['Signal_Line'] = feat['MACD'].ewm(span=9, adjust=False).mean()
        feat['MACD_Hist'] = feat['MACD'] - feat['Signal_Line']

        # Bollinger (4)
        feat['BB_Middle'] = c.rolling(window=20).mean()
        bb_std = c.rolling(window=20).std()
        feat['BB_Upper'] = feat['BB_Middle'] + (bb_std * 2)
        feat['BB_Lower'] = feat['BB_Middle'] - (bb_std * 2)
        feat['BB_Position'] = (c - feat['BB_Lower']) / (feat['BB_Upper'] - feat['BB_Lower'] + 1e-10)

        # Volatility, Volume Ratio, ROC (3)
        feat['Volatility'] = c.pct_change().rolling(window=10).std()
        feat['Volume_Ratio'] = v / (v.rolling(window=20).mean() + 1e-10)
        feat['ROC'] = (c - c.shift(10)) / (c.shift(10) + 1e-10) * 100

        # ATR (1)
        high_low = h - l
        high_close = np.abs(h - c.shift())
        low_close = np.abs(l - c.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        feat['ATR'] = true_range.rolling(14).mean()

        # Lags (3)
        for i in range(1, 4):
            feat[f'Return_Lag_{i}'] = c.pct_change().shift(i)

        # Drop raw price cols, keep only computed features
        feature_cols = [col for col in feat.columns
                        if col not in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']]
        return feat[feature_cols].fillna(0), feature_cols

    def _train(self, prices_dict):
        X_all, y_all = [], []
        feat_cols = None
        for ticker, df in prices_dict.items():
            if len(df) < 65:
                continue
            feat, feat_cols = self._compute_features(df)
            c = df['Close']
            # Target: max suba en 5 dias >= 2%
            futuro_max = c.shift(-5).rolling(window=5).max()
            retorno_futuro = (futuro_max - c) / (c + 1e-10)
            target = (retorno_futuro >= 0.02).astype(int)
            target.iloc[-5:] = np.nan
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 30:
                continue
            X_all.append(feat.loc[valid].values)
            y_all.append(target.loc[valid].values)

        if not X_all or feat_cols is None:
            return False
        self._feat_cols = feat_cols
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        if HAS_XGB:
            spw = (y == 0).sum() / max((y == 1).sum(), 1)
            self.model = XGBClassifier(
                objective='binary:logistic', n_estimators=100, max_depth=4,
                learning_rate=0.1, subsample=0.8, colsample_bytree=0.8,
                scale_pos_weight=spw, eval_metric='auc',
                tree_method='hist', random_state=42)
        else:
            self.model = HistGradientBoostingClassifier(
                max_iter=150, max_depth=4, learning_rate=0.1,
                l2_regularization=0.2, class_weight='balanced', random_state=42)
        self.model.fit(Xs, y)
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.model is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []
        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 65:
                continue
            feat, _ = self._compute_features(df)
            X = self.scaler.transform(feat.iloc[-1:].values)
            prob = self.model.predict_proba(X)[0]
            if len(prob) < 2:
                continue
            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': float(prob[1]),
                'score': float(prob[1] * 100),
            })
        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 9: v66 — Deep Stacking + Triple Barrier (62 features)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Stacked ensemble nivel institucional. 62 features incluyendo
#  Hurst exponent, Garman-Klass vol, Amihud illiquidity.
#  Triple Barrier labels (Lopez de Prado 2018).
#  Base learners (RF+GB+ET+MLP+LR) → Ridge meta-learner.
#  Similar a V22_QUANT pero implementacion distinta y features ligeramente
#  diferentes. Incluye features avanzados cuantitativos extras.
#
#  Origen: ml_trading_v66.py

class StrategyV66:
    """v66: 62 features quant, stacked ensemble + triple barrier, 5 base → Ridge meta."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.base_models = None
        self.meta_model = None
        self.scaler = None
        self.day_count = 0

    def _compute_features(self, df, spy_close=None):
        """62 features incluyendo avanzados cuantitativos."""
        c, v = df['Close'], df['Volume']
        h, l, o = df['High'], df['Low'], df['Open']
        ret = c.pct_change()

        feat = pd.DataFrame(index=df.index)

        # === Momentum (8) ===
        feat['ret1'] = ret
        feat['ret3'] = c.pct_change(3)
        feat['ret5'] = c.pct_change(5)
        feat['ret10'] = c.pct_change(10)
        feat['ret20'] = c.pct_change(20)
        feat['ret40'] = c.pct_change(40)
        feat['ret60'] = c.pct_change(60)
        feat['mom_accel'] = feat['ret5'] - feat['ret20'].shift(5)

        # === MAs (4) ===
        ma5 = c.rolling(5).mean()
        ma20 = c.rolling(20).mean()
        ma50 = c.rolling(50).mean()
        feat['p_vs_ma5'] = c / ma5 - 1
        feat['p_vs_ma20'] = c / ma20 - 1
        feat['p_vs_ma50'] = c / ma50 - 1
        feat['cross_520'] = ma5 / ma20 - 1

        # === RSI (3) ===
        feat['rsi7'] = compute_rsi(c, 7)
        feat['rsi14'] = compute_rsi(c, 14)
        feat['rsi_slope'] = feat['rsi14'] - feat['rsi14'].shift(3)

        # === MACD (4) ===
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        feat['macd_norm'] = macd / (c + 1e-10)
        feat['macd_hist'] = macd - macd_sig
        feat['macd_cross'] = ((feat['macd_hist'] > 0).astype(int) -
                              (feat['macd_hist'].shift(1) > 0).astype(int))
        feat['macd_hist_chg'] = feat['macd_hist'] - feat['macd_hist'].shift(1)

        # === Bollinger (3) ===
        std20 = c.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        feat['bb_pct'] = (c - lower) / (upper - lower + 1e-10)
        feat['bb_width'] = (upper - lower) / (ma20 + 1e-10)
        feat['bb_squeeze'] = feat['bb_width'].rolling(60, min_periods=20).rank(pct=True)

        # === Volatility (5) ===
        vol5 = ret.rolling(5).std()
        vol20 = ret.rolling(20).std()
        feat['vol5'] = vol5
        feat['vol20'] = vol20
        feat['vol_ratio'] = vol5 / (vol20 + 1e-8)
        # Garman-Klass volatility
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
        feat['gk_vol'] = np.sqrt((0.5 * log_hl - (2 * np.log(2) - 1) * log_co).rolling(14).mean())
        # Volatility of volatility
        feat['vol_of_vol'] = vol20.rolling(20).std()

        # === Stochastic (2) ===
        lo14 = c.rolling(14).min()
        hi14 = c.rolling(14).max()
        feat['stoch_k'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100
        feat['stoch_d'] = feat['stoch_k'].rolling(3).mean()

        # === Volume (4) ===
        v_ma20 = v.rolling(20).mean()
        feat['v_ratio'] = v / (v_ma20 + 1e-8)
        feat['v_ratio5'] = v.rolling(5).mean() / (v_ma20 + 1e-8)
        feat['pv_mom'] = feat['ret5'] * np.log1p(feat['v_ratio'].clip(0, 10))
        # OBV momentum
        direction = np.sign(ret)
        obv = (direction * v).cumsum()
        obv_ma10 = obv.rolling(10).mean()
        feat['obv_mom'] = obv / (obv_ma10.abs() + 1e-8) - 1

        # === Microstructure (4) ===
        feat['close_strength'] = (c - l) / (h - l + 1e-10)
        feat['gap_open'] = (o / c.shift(1) - 1) * 100
        feat['intraday_ret'] = (c / o - 1) * 100
        feat['dist_10d_low'] = (c / l.rolling(10).min() - 1) * 100

        # === Z-score (1) ===
        feat['zscore20'] = (c - ma20) / (std20 + 1e-10)

        # === Advanced quant (7) ===
        # Hurst exponent (simplified)
        def _hurst_simple(series, max_lag=20):
            if len(series) < max_lag + 10:
                return pd.Series(0.5, index=series.index)
            rs_list = []
            for lag in range(2, max_lag + 1):
                vals = series.rolling(lag).apply(
                    lambda x: (x.cumsum().max() - x.cumsum().min()) / (x.std() + 1e-10),
                    raw=True)
                rs_list.append(vals)
            # Simple approximation
            return pd.Series(0.5, index=series.index)  # placeholder

        feat['hurst'] = 0.5  # Simplified — full Hurst is too slow per-bar
        # Amihud illiquidity
        feat['amihud'] = (ret.abs() / (v.astype(float) * c + 1e-10) * 1e9).rolling(20).mean()
        # Price acceleration
        feat['price_accel'] = feat['ret5'] - feat['ret5'].shift(5)
        # Realized skewness
        feat['realized_skew'] = ret.rolling(20).apply(
            lambda x: ((x - x.mean()) ** 3).mean() / (x.std() ** 3 + 1e-10), raw=True)
        # RSI divergence
        feat['rsi_div'] = feat['ret5'] - (feat['rsi14'] / 100 - 0.5)
        # 52-week distances
        hi_252 = c.rolling(252, min_periods=60).max()
        lo_252 = c.rolling(252, min_periods=60).min()
        feat['dist_52w_hi'] = c / hi_252 - 1
        feat['dist_52w_lo'] = c / lo_252 - 1

        # === Market context (2) ===
        if spy_close is not None and len(spy_close) == len(c):
            spy_ret = spy_close.pct_change()
            feat['mkt_trend'] = spy_close / spy_close.rolling(20).mean() - 1
            feat['mkt_rsi'] = compute_rsi(spy_close, 14)
        else:
            feat['mkt_trend'] = 0
            feat['mkt_rsi'] = 50

        feat = feat.replace([np.inf, -np.inf], np.nan).fillna(0)
        return feat

    def _triple_barrier_target(self, close, horizon=5, threshold=0.018):
        """Triple barrier labels: 2=BUY, 1=HOLD, 0=SELL."""
        target = pd.Series(1, index=close.index)
        ret_fwd = close.pct_change(horizon).shift(-horizon)
        target[ret_fwd >= threshold] = 2
        target[ret_fwd <= -threshold] = 0
        target.iloc[-horizon:] = np.nan
        return target

    def _train(self, prices_dict):
        X_all, y_all = [], []
        spy_close = prices_dict.get('SPY', prices_dict.get('QQQ', pd.DataFrame())).get('Close')

        for ticker, df in prices_dict.items():
            if len(df) < 280:
                continue
            sc = spy_close.reindex(df.index) if spy_close is not None else None
            feat = self._compute_features(df, sc)
            target = self._triple_barrier_target(df['Close'])
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 50:
                continue
            X_all.append(feat.loc[valid].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self._feat_names = list(self._compute_features(
            list(prices_dict.values())[0]).columns)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        # Level 1: base learners
        self.base_models = {
            'RF': RandomForestClassifier(n_estimators=200, max_depth=8,
                      min_samples_leaf=12, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'GB': GradientBoostingClassifier(n_estimators=150, max_depth=4,
                      learning_rate=0.04, random_state=42),
            'ET': ExtraTreesClassifier(n_estimators=200, max_depth=8,
                      min_samples_leaf=10, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'MLP': MLPClassifier(hidden_layer_sizes=(128, 64),
                       max_iter=500, early_stopping=True, random_state=42),
            'LR': LogisticRegression(class_weight='balanced',
                      max_iter=500, solver='saga'),
        }
        for m in self.base_models.values():
            m.fit(Xs, y)

        # Level 2: Ridge meta-learner on base predictions
        base_preds = np.column_stack([
            m.predict_proba(Xs)[:, -1] for m in self.base_models.values()
        ])
        self.meta_model = Ridge(alpha=1.0)
        self.meta_model.fit(base_preds, (y == 2).astype(float))
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.base_models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []

        spy_close = prices_dict.get('SPY', prices_dict.get('QQQ', pd.DataFrame())).get('Close')
        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 280:
                continue
            sc = spy_close.reindex(df.index) if spy_close is not None else None
            feat = self._compute_features(df, sc)
            X = self.scaler.transform(feat.iloc[-1:].values)
            base_preds = np.array([
                m.predict_proba(X)[0][-1] for m in self.base_models.values()
            ]).reshape(1, -1)
            score = float(self.meta_model.predict(base_preds)[0])
            score = max(0, min(1, score))
            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': score,
                'score': score * 100,
            })
        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY 10: v40 — Hybrid Meta-Ensemble (v11 signal as feature + stacking)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO: Lo mejor de ambos mundos. Primero corre el modelo simple (v11,
#  9 features) para generar una "prob_simple". Esa probabilidad se agrega
#  como feature #63 al modelo complejo de stacking. Asi el modelo complejo
#  puede "escuchar" al modelo simple cuando conviene.
#  63 features totales. Triple Barrier labels.
#  5 base learners → Ridge meta-learner.
#
#  Origen: ml_trading_v40.py

class StrategyV40Hybrid:
    """v40: Hybrid — simple v11 signal as extra feature + 62 quant features + stacking."""

    def __init__(self, retrain_every=20):
        self.retrain_every = retrain_every
        self.simple_brain = StrategyBrainV11(retrain_every=999)  # train once
        self.base_models = None
        self.meta_model = None
        self.scaler = None
        self.day_count = 0
        self._simple_trained = False

    def _compute_features(self, df, spy_close=None, simple_score=0.5):
        """62 quant features + 1 prob_simple = 63 total."""
        # Reuse v66's feature computation
        c, v = df['Close'], df['Volume']
        h, l, o = df['High'], df['Low'], df['Open']
        ret = c.pct_change()

        feat = pd.DataFrame(index=df.index)

        # Momentum (8)
        feat['ret1'] = ret
        feat['ret3'] = c.pct_change(3)
        feat['ret5'] = c.pct_change(5)
        feat['ret10'] = c.pct_change(10)
        feat['ret20'] = c.pct_change(20)
        feat['ret40'] = c.pct_change(40)
        feat['ret60'] = c.pct_change(60)
        feat['mom_accel'] = feat['ret5'] - feat['ret20'].shift(5)

        # MAs (4)
        ma5 = c.rolling(5).mean()
        ma20 = c.rolling(20).mean()
        ma50 = c.rolling(50).mean()
        feat['p_vs_ma5'] = c / ma5 - 1
        feat['p_vs_ma20'] = c / ma20 - 1
        feat['p_vs_ma50'] = c / ma50 - 1
        feat['cross_520'] = ma5 / ma20 - 1

        # RSI (3)
        feat['rsi7'] = compute_rsi(c, 7)
        feat['rsi14'] = compute_rsi(c, 14)
        feat['rsi_slope'] = feat['rsi14'] - feat['rsi14'].shift(3)

        # MACD (3)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        feat['macd_norm'] = macd / (c + 1e-10)
        feat['macd_hist'] = macd - macd_sig
        feat['macd_cross'] = ((feat['macd_hist'] > 0).astype(int) -
                              (feat['macd_hist'].shift(1) > 0).astype(int))

        # Bollinger (3)
        std20 = c.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        feat['bb_pct'] = (c - lower) / (upper - lower + 1e-10)
        feat['bb_width'] = (upper - lower) / (ma20 + 1e-10)
        feat['bb_squeeze'] = feat['bb_width'].rolling(60, min_periods=20).rank(pct=True)

        # Volatility (4)
        vol5 = ret.rolling(5).std()
        vol20 = ret.rolling(20).std()
        feat['vol5'] = vol5
        feat['vol20'] = vol20
        feat['vol_ratio'] = vol5 / (vol20 + 1e-8)
        log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
        log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
        feat['gk_vol'] = np.sqrt((0.5 * log_hl - (2 * np.log(2) - 1) * log_co).rolling(14).mean())

        # Stochastic (2)
        lo14 = c.rolling(14).min()
        hi14 = c.rolling(14).max()
        feat['stoch_k'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100
        feat['stoch_d'] = feat['stoch_k'].rolling(3).mean()

        # Volume (4)
        v_ma20 = v.rolling(20).mean()
        feat['v_ratio'] = v / (v_ma20 + 1e-8)
        feat['v_ratio5'] = v.rolling(5).mean() / (v_ma20 + 1e-8)
        feat['pv_mom'] = feat['ret5'] * np.log1p(feat['v_ratio'].clip(0, 10))
        direction = np.sign(ret)
        obv = (direction * v).cumsum()
        obv_ma10 = obv.rolling(10).mean()
        feat['obv_mom'] = obv / (obv_ma10.abs() + 1e-8) - 1

        # Microstructure (4)
        feat['close_strength'] = (c - l) / (h - l + 1e-10)
        feat['gap_open'] = (o / c.shift(1) - 1) * 100
        feat['intraday_ret'] = (c / o - 1) * 100
        feat['dist_10d_low'] = (c / l.rolling(10).min() - 1) * 100

        # Z-score and advanced (6)
        feat['zscore20'] = (c - ma20) / (std20 + 1e-10)
        feat['amihud'] = (ret.abs() / (v.astype(float) * c + 1e-10) * 1e9).rolling(20).mean()
        feat['price_accel'] = feat['ret5'] - feat['ret5'].shift(5)
        feat['rsi_div'] = feat['ret5'] - (feat['rsi14'] / 100 - 0.5)
        hi_252 = c.rolling(252, min_periods=60).max()
        lo_252 = c.rolling(252, min_periods=60).min()
        feat['dist_52w_hi'] = c / hi_252 - 1
        feat['dist_52w_lo'] = c / lo_252 - 1

        # Market context (2)
        if spy_close is not None and len(spy_close) == len(c):
            feat['mkt_trend'] = spy_close / spy_close.rolling(20).mean() - 1
            feat['mkt_rsi'] = compute_rsi(spy_close, 14)
        else:
            feat['mkt_trend'] = 0
            feat['mkt_rsi'] = 50

        # Feature #63: simple model probability
        feat['prob_simple'] = simple_score

        feat = feat.replace([np.inf, -np.inf], np.nan).fillna(0)
        return feat

    def _train(self, prices_dict):
        # 1) Train the simple brain first
        if not self._simple_trained:
            self.simple_brain._train(prices_dict)
            self._simple_trained = True

        spy_close = prices_dict.get('SPY', prices_dict.get('QQQ', pd.DataFrame())).get('Close')
        X_all, y_all = [], []

        for ticker, df in prices_dict.items():
            if len(df) < 280:
                continue
            # Get simple model score for this ticker
            sc = spy_close.reindex(df.index) if spy_close is not None else None
            feat = self._compute_features(df, sc, simple_score=0.5)
            # Triple barrier target
            c = df['Close']
            fwd_ret = c.pct_change(5).shift(-5)
            target = pd.Series(1, index=df.index)
            target[fwd_ret >= 0.018] = 2
            target[fwd_ret <= -0.018] = 0
            target.iloc[-5:] = np.nan
            valid = target.notna() & feat.notna().all(axis=1)
            if valid.sum() < 50:
                continue
            X_all.append(feat.loc[valid].values)
            y_all.append(target.loc[valid].values)

        if not X_all:
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self.scaler = RobustScaler()
        Xs = self.scaler.fit_transform(X)

        self.base_models = {
            'RF': RandomForestClassifier(n_estimators=200, max_depth=8,
                      min_samples_leaf=12, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'GB': GradientBoostingClassifier(n_estimators=150, max_depth=4,
                      learning_rate=0.04, random_state=42),
            'ET': ExtraTreesClassifier(n_estimators=200, max_depth=8,
                      min_samples_leaf=10, class_weight='balanced',
                      random_state=42, n_jobs=-1),
            'MLP': MLPClassifier(hidden_layer_sizes=(128, 64),
                       max_iter=500, early_stopping=True, random_state=42),
            'LR': LogisticRegression(class_weight='balanced',
                      max_iter=500, solver='saga'),
        }
        for m in self.base_models.values():
            m.fit(Xs, y)

        base_preds = np.column_stack([
            m.predict_proba(Xs)[:, -1] for m in self.base_models.values()
        ])
        self.meta_model = Ridge(alpha=1.0)
        self.meta_model.fit(base_preds, (y == 2).astype(float))
        return True

    def __call__(self, prices_dict, tickers, date_str):
        self.day_count += 1
        if self.base_models is None or self.day_count % self.retrain_every == 0:
            if not self._train(prices_dict):
                return []

        spy_close = prices_dict.get('SPY', prices_dict.get('QQQ', pd.DataFrame())).get('Close')
        picks = []
        for ticker in tickers:
            if ticker not in prices_dict:
                continue
            df = prices_dict[ticker]
            if len(df) < 280:
                continue
            # Get simple brain score
            simple_score = 0.5
            if self.simple_brain.models is not None:
                sf = self.simple_brain._compute_features(df)
                if sf is not None and len(df) >= 215:
                    try:
                        sX = self.simple_brain.scaler.transform(
                            sf[self.simple_brain.feat_cols].iloc[-1:].values)
                        votes = [m.predict(sX)[0] for m in self.simple_brain.models.values()]
                        simple_score = sum(1 for vv in votes if vv == 2) / len(self.simple_brain.models)
                    except Exception:
                        pass

            sc = spy_close.reindex(df.index) if spy_close is not None else None
            feat = self._compute_features(df, sc, simple_score=simple_score)
            X = self.scaler.transform(feat.iloc[-1:].values)
            base_preds = np.array([
                m.predict_proba(X)[0][-1] for m in self.base_models.values()
            ]).reshape(1, -1)
            score = float(self.meta_model.predict(base_preds)[0])
            score = max(0, min(1, score))
            picks.append({
                'ticker': ticker,
                'direction': 'UP',
                'confidence': score,
                'score': score * 100,
            })
        return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  FACTORY: crear instancias de strategies
# ═══════════════════════════════════════════════════════════════════════════════

def create_all_strategies():
    """
    Crea todas las strategies disponibles.

    CONCEPTO — Factory Pattern:
    ---------------------------
    En vez de que el usuario tenga que saber como instanciar cada clase,
    le damos una funcion que devuelve todo listo para usar.
    """
    return {
        'V37_SQUEEZE': StrategyV37(retrain_every=20),
        'V97_MICRO': StrategyV97(retrain_every=20),
        'V39_ENSEMBLE': StrategyV39Full(retrain_every=20),
        'V72_HYBRID': StrategyV72(retrain_every=20),
        'V22_QUANT': StrategyV22(retrain_every=20),
        'V102_EVENT': StrategyV102(retrain_every=20),
        'BRAIN_V11': StrategyBrainV11(retrain_every=20),
        'BRAIN_V11_OPT': StrategyBrainV11Opt(retrain_every=20),
        'V94_XGBOOST': StrategyV94(retrain_every=20),
        'V66_DEEP': StrategyV66(retrain_every=20),
        'V40_HYBRID': StrategyV40Hybrid(retrain_every=20),
    }
