//+------------------------------------------------------------------+
//|                                            UJCoilLab_USDJPY.mq5  |
//| USDJPY compression-breakout ("coil") lab — 36 presets            |
//| Built from UJ_research_2026-07_rerun.md (real ticks Jan-Jul 2026)|
//| Magic = 800000 + InpStrategyID                                   |
//| Tester: USDJPY chart, M1, "Every tick based on real ticks"       |
//| IDs 30-33 need EURJPY/GBPJPY/AUDJPY/CHFJPY in Market Watch       |
//+------------------------------------------------------------------+
#property copyright "de6 lab"
#property version   "1.00"

#include <Trade/Trade.mqh>

input int    InpStrategyID    = 1;      // strategy ID 1..36 (see UJCoilLab_strategy_map.md)
input double InpLots          = 0.01;   // fixed lots (used when risk% = 0)
input double InpRiskPct       = 0.0;    // risk % of equity per trade (needs SL; 0 = fixed lots)
input double InpMaxSpreadPips = 2.5;    // skip entries when spread above this (pips)
input int    InpMagicBase     = 800000; // magic base

CTrade trade;

#define PIP 0.01

//--- strategy parameter block (filled from ID table)
struct Params
{
   int    family;        // 1=roll-coil 2=calendar-NR 3=jpy-lag 4=expanded-control
   double cr;            // compression ratio vs median
   int    holdMin;       // timed hold, minutes
   int    medWinH;       // median window, hourly samples
   int    evalStepMin;   // evaluation cadence, minutes (60 default)
   double bufPips;       // breakout buffer
   int    slMode;        // 0=none 1=fixed pips 2=frac of box 3=far box edge
   double slVal;         // pips or fraction
   int    cooldownMin;   // min minutes between entries
   int    dirFilter;     // 0=both 1=longs only -1=shorts only
   bool   reversed;      // trade opposite direction (control)
   int    entryH0;       // allowed entry hours [h0,h1) server, -1 = all
   int    entryH1;
   int    nrK;           // calendar family: NR-k
   double lagZ;          // jpy-lag: basket z threshold
   double lagUjz;        // jpy-lag: max own |z|
};
Params P;

//--- state: roll-coil family
double  g_r24buf[200];      // ring buffer of hourly R24 samples (pips)
int     g_r24n = 0;         // samples stored (capped at medWinH)
int     g_r24pos = 0;       // next write pos
datetime g_lastEvalBar = 0; // last H1(or step) boundary processed
bool    g_flag = false;     // compression flag active
double  g_boxHi = 0, g_boxLo = 0;
datetime g_flagTime = 0;    // when flag was set (watch 24h)
datetime g_lastM1 = 0;
datetime g_lastEntry = 0;
datetime g_entryTime = 0;   // open position entry time
bool    g_warmed = false;

//--- calendar family state
double  g_dayHi[10], g_dayLo[10];   // completed day ranges ring (0 = yesterday)
int     g_dayCount = 0;
int     g_curDayD = -1;
double  g_curHi = 0, g_curLo = 0;
bool    g_calArmed = false;         // yesterday was NR-k
double  g_calHi = 0, g_calLo = 0;
bool    g_calDone = false;          // one trade per day max

//--- jpy-lag family state
string  g_cross[4] = {"EURJPY","GBPJPY","AUDJPY","CHFJPY"};
#define LAGBUF 5760
double  g_mv[5][LAGBUF];    // 15m log-move samples per symbol (4 crosses + UJ)
int     g_mvn[5];
int     g_mvpos[5];
datetime g_lastM5 = 0;

//+------------------------------------------------------------------+
void SetDefaults()
{
   P.family=1; P.cr=0.60; P.holdMin=480; P.medWinH=120; P.evalStepMin=60;
   P.bufPips=0; P.slMode=0; P.slVal=0; P.cooldownMin=1440; P.dirFilter=0;
   P.reversed=false; P.entryH0=-1; P.entryH1=-1; P.nrK=4; P.lagZ=2.0; P.lagUjz=0.3;
}

bool Configure(int id)
{
   SetDefaults();
   switch(id)
   {
      // ---- family A: rolling-24h coil breakout (validated core region) ----
      case 1:  break;                                              // cr0.60 h8 BASE
      case 2:  P.cr=0.55; break;                                   // cr0.55 h8
      case 3:  P.cr=0.50; break;                                   // cr0.50 h8
      case 4:  P.holdMin=240; break;                               // cr0.60 h4
      case 5:  P.holdMin=720; break;                               // cr0.60 h12
      case 6:  P.cr=0.55; P.holdMin=240; break;                    // cr0.55 h4
      case 7:  P.cr=0.55; P.holdMin=720; break;                    // cr0.55 h12
      case 8:  P.bufPips=3; break;                                 // base + buffer 3p (best refinement)
      case 9:  P.cr=0.55; P.bufPips=3; break;
      case 10: P.slMode=1; P.slVal=20; break;                      // base + SL 20p
      case 11: P.slMode=2; P.slVal=0.5; break;                     // base + SL 0.5×box
      case 12: P.slMode=1; P.slVal=35; break;                      // base + SL 35p
      case 13: P.dirFilter=1; break;                               // longs only (regime probe)
      case 14: P.dirFilter=-1; break;                              // shorts only (regime probe)
      case 15: P.medWinH=96; break;                                // median window 96h
      case 16: P.medWinH=168; break;                               // median window 168h
      case 17: break;                                              // base, run w/ InpMaxSpreadPips=1.5
      case 18: P.entryH0=2; P.entryH1=22; break;                   // entries 02-22h only
      case 19: P.slMode=1; P.slVal=20; break;                      // base+SL20, run w/ InpRiskPct=1.0

      // ---- family B: calendar NR-k breakout (independent formulation) ----
      case 20: P.family=2; P.nrK=4; P.holdMin=480; break;          // NR4 h8
      case 21: P.family=2; P.nrK=4; P.holdMin=720; break;          // NR4 h12
      case 22: P.family=2; P.nrK=3; P.holdMin=480; break;          // NR3 h8
      case 23: P.family=2; P.nrK=4; P.holdMin=480; P.entryH0=3; P.entryH1=16; break;

      // ---- family C: canaries & must-lose controls ----
      case 24: P.cr=0.65; break;                                   // dilution canary (expected NEGATIVE)
      case 25: P.cr=0.80; break;                                   // dilution control (expected NEGATIVE)
      case 26: P.reversed=true; break;                             // reversed base (MUST LOSE)
      case 27: P.family=4; break;                                  // expanded-range placebo (MUST LOSE/flat)
      case 28: P.cooldownMin=720; break;                           // 12h cooldown canary (expected NEGATIVE)
      case 29: P.evalStepMin=30; break;                            // 30-min eval canary (expected NEGATIVE)
      case 30: P.family=3; P.lagZ=2.0;  P.holdMin=15; P.cooldownMin=0; break; // JPY-lag short (grid-falsified canary)
      case 31: P.family=3; P.lagZ=1.75; P.holdMin=15; P.cooldownMin=0; break; // JPY-lag short z1.75
      case 32: P.family=3; P.lagZ=2.0;  P.holdMin=30; P.cooldownMin=0; break; // JPY-lag short hold30
      case 33: P.family=3; P.lagZ=2.0;  P.holdMin=15; P.cooldownMin=0; P.reversed=true; break; // lag reversed (MUST LOSE)

      // ---- combined / sizing candidates ----
      case 34: P.bufPips=3; P.slMode=1; P.slVal=20; break;         // buf3+SL20, run w/ InpRiskPct=1.0
      case 35: P.cr=0.55; P.bufPips=3; P.holdMin=480; break;       // conservative prod candidate
      case 36: P.cr=0.60; P.bufPips=3; P.holdMin=240; break;       // fast prod candidate
      default: return false;
   }
   return true;
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(!Configure(InpStrategyID))
   {
      Print("UJCoilLab: bad InpStrategyID ", InpStrategyID);
      return INIT_PARAMETERS_INCORRECT;
   }
   trade.SetExpertMagicNumber(InpMagicBase + InpStrategyID);
   trade.SetDeviationInPoints(20);
   if(P.family==3)
      for(int s=0;s<4;s++)
         if(!SymbolSelect(g_cross[s], true))
            Print("UJCoilLab: warning, cannot select ", g_cross[s]);
   ArrayInitialize(g_r24buf, 0.0);
   for(int s=0;s<5;s++){ g_mvn[s]=0; g_mvpos[s]=0; }
   Print("UJCoilLab id=", InpStrategyID, " family=", P.family,
         " magic=", InpMagicBase+InpStrategyID);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
double SpreadPips()
{
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return 1e9;
   return (tk.ask - tk.bid)/PIP;
}

double MedianOf(int cnt)
{
   if(cnt<=0) return 0;
   double tmp[];
   ArrayResize(tmp, cnt);
   for(int k=0;k<cnt;k++) tmp[k]=g_r24buf[k];  // buffer holds most-recent cnt in slots 0..cnt-1 shifted below
   ArraySort(tmp);
   if(cnt%2==1) return tmp[cnt/2];
   return 0.5*(tmp[cnt/2-1]+tmp[cnt/2]);
}

// push newest R24 sample, keeping newest P.medWinH samples in slots 0..n-1
void PushR24(double v)
{
   int cap = P.medWinH;
   if(g_r24n < cap){ g_r24buf[g_r24n]=v; g_r24n++; }
   else
   {
      for(int k=0;k<cap-1;k++) g_r24buf[k]=g_r24buf[k+1];
      g_r24buf[cap-1]=v;
   }
}

// 24h high/low box ending now, from M1 history
bool Box24(datetime now, double &bhi, double &blo)
{
   double hh[], ll[];
   datetime from = now - 86400;
   int n1 = CopyHigh(_Symbol, PERIOD_M1, from, now, hh);
   int n2 = CopyLow (_Symbol, PERIOD_M1, from, now, ll);
   if(n1<600 || n2<600) return false;
   bhi = hh[ArrayMaximum(hh)];
   blo = ll[ArrayMinimum(ll)];
   return true;
}

//+------------------------------------------------------------------+
bool HavePosition()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk>0 && PositionSelectByTicket(tk))
         if(PositionGetInteger(POSITION_MAGIC)==InpMagicBase+InpStrategyID
            && PositionGetString(POSITION_SYMBOL)==_Symbol)
            return true;
   }
   return false;
}

void CloseAll()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk>0 && PositionSelectByTicket(tk))
         if(PositionGetInteger(POSITION_MAGIC)==InpMagicBase+InpStrategyID
            && PositionGetString(POSITION_SYMBOL)==_Symbol)
            trade.PositionClose(tk);
   }
}

double CalcLots(double slPips)
{
   if(InpRiskPct<=0 || slPips<=0) return InpLots;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double tickVal = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0 || tickSz<=0) return InpLots;
   double valPerPipPerLot = tickVal * (PIP/tickSz);
   double lots = eq*InpRiskPct/100.0/(slPips*valPerPipPerLot);
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double stepL= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots/stepL)*stepL;
   return MathMin(maxL, MathMax(minL, lots));
}

bool EntryHourOK(datetime now)
{
   if(P.entryH0<0) return true;
   MqlDateTime dt; TimeToStruct(now, dt);
   return (dt.hour>=P.entryH0 && dt.hour<P.entryH1);
}

void OpenDir(int dir, double slPips)
{
   if(P.reversed) dir = -dir;
   if(P.dirFilter!=0 && dir!=P.dirFilter) return;
   if(SpreadPips()>InpMaxSpreadPips) return;
   MqlTick tk; if(!SymbolInfoTick(_Symbol,tk)) return;
   double lots = CalcLots(slPips);
   double sl = 0;
   if(P.slMode>0 && slPips>0)
      sl = (dir>0)? tk.ask - slPips*PIP : tk.bid + slPips*PIP;
   bool ok = (dir>0)? trade.Buy(lots,_Symbol,0.0,sl,0.0)
                    : trade.Sell(lots,_Symbol,0.0,sl,0.0);
   if(ok){ g_lastEntry=TimeCurrent(); g_entryTime=TimeCurrent(); }
}

//+------------------------------------------------------------------+
//| family A/4: evaluate compression state on step boundary          |
//+------------------------------------------------------------------+
void EvalCoil(datetime now)
{
   datetime stepBar = now - (now % (P.evalStepMin*60));
   if(stepBar==g_lastEvalBar) return;
   g_lastEvalBar = stepBar;
   double bhi, blo;
   if(!Box24(now, bhi, blo)) return;
   double r24 = (bhi-blo)/PIP;
   PushR24(r24);
   int need = P.medWinH/3;
   if(g_r24n < need) return;
   g_warmed = true;
   double med = MedianOf(g_r24n);
   bool flagNow;
   if(P.family==4) flagNow = (r24 >= 1.2*med);      // expanded-range placebo
   else            flagNow = (r24 <= P.cr*med);
   if(flagNow && !g_flag)
   {
      g_flag=true; g_flagTime=now; g_boxHi=bhi; g_boxLo=blo;
   }
   else if(g_flag && now-g_flagTime>86400)
      g_flag=false;   // watch window expired
}

// M1-close breakout check for family A/B
void CheckBreakoutA()
{
   if(!g_flag) return;
   if(HavePosition()) return;
   if(TimeCurrent()-g_lastEntry < P.cooldownMin*60) return;
   if(!EntryHourOK(TimeCurrent())) return;
   double h1 = iHigh(_Symbol, PERIOD_M1, 1);
   double l1 = iLow (_Symbol, PERIOD_M1, 1);
   int dir=0;
   if(h1 > g_boxHi + P.bufPips*PIP) dir=1;
   else if(l1 < g_boxLo - P.bufPips*PIP) dir=-1;
   if(dir==0) return;
   double slPips=0;
   if(P.slMode==1) slPips=P.slVal;
   else if(P.slMode==2) slPips=(g_boxHi-g_boxLo)/PIP*P.slVal;
   else if(P.slMode==3) slPips=(dir>0)? (iClose(_Symbol,PERIOD_M1,1)-g_boxLo)/PIP
                                      : (g_boxHi-iClose(_Symbol,PERIOD_M1,1))/PIP;
   g_flag=false;               // one shot per flag
   OpenDir(dir, slPips);
}

//+------------------------------------------------------------------+
//| family B: calendar-day NR-k                                       |
//+------------------------------------------------------------------+
void EvalCalendar(datetime now)
{
   MqlDateTime dt; TimeToStruct(now, dt);
   int dkey = (int)(now/86400);
   // track intraday 03-22h high/low
   if(dkey != g_curDayD)
   {
      // day rolled: store completed day if it had data
      if(g_curDayD>0 && g_curHi>0)
      {
         for(int k=9;k>0;k--){ g_dayHi[k]=g_dayHi[k-1]; g_dayLo[k]=g_dayLo[k-1]; }
         g_dayHi[0]=g_curHi; g_dayLo[0]=g_curLo;
         if(g_dayCount<10) g_dayCount++;
         // arm if yesterday (slot 0) is NR-k vs slots 1..k-... : range < min of prior (nrK-1) days
         if(g_dayCount >= P.nrK)
         {
            double y = g_dayHi[0]-g_dayLo[0];
            double mn = 1e18;
            for(int k=1;k<P.nrK;k++) mn = MathMin(mn, g_dayHi[k]-g_dayLo[k]);
            g_calArmed = (y <= mn);
            g_calHi = g_dayHi[0]; g_calLo = g_dayLo[0]; g_calDone=false;
         }
      }
      g_curDayD = dkey; g_curHi=0; g_curLo=0;
   }
   if(dt.hour>=3 && dt.hour<22)
   {
      double h1=iHigh(_Symbol,PERIOD_M1,1), l1=iLow(_Symbol,PERIOD_M1,1);
      if(g_curHi==0 || h1>g_curHi) g_curHi=h1;
      if(g_curLo==0 || l1<g_curLo) g_curLo=l1;
   }
}

void CheckBreakoutB()
{
   if(!g_calArmed || g_calDone) return;
   if(HavePosition()) return;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   int h0 = (P.entryH0>=0)? P.entryH0 : 3;
   int h1_ = (P.entryH1>=0)? P.entryH1 : 22;
   if(dt.hour<h0 || dt.hour>=h1_) return;
   double bh1=iHigh(_Symbol,PERIOD_M1,1), bl1=iLow(_Symbol,PERIOD_M1,1);
   int dir=0;
   if(bh1>g_calHi) dir=1;
   else if(bl1<g_calLo) dir=-1;
   if(dir==0) return;
   g_calDone=true;
   OpenDir(dir, 0);
}

//+------------------------------------------------------------------+
//| family C: JPY-basket lag (canary — grid-falsified in research)   |
//+------------------------------------------------------------------+
double CloseM5(string sym, int shift)
{
   return iClose(sym, PERIOD_M5, shift);
}

void EvalLag(datetime now)
{
   datetime m5 = now - (now % 300);
   if(m5==g_lastM5) return;
   g_lastM5 = m5;
   // 15m log-moves at M5 close: close[1] vs close[4] (3 completed M5 bars)
   double z[5]; bool okAll=true;
   for(int s=0;s<5;s++)
   {
      string sym = (s<4)? g_cross[s] : _Symbol;
      double c1=CloseM5(sym,1), c4=CloseM5(sym,4);
      if(c1<=0 || c4<=0){ okAll=false; continue; }
      double mv = MathLog(c1/c4);
      int pos=g_mvpos[s];
      g_mv[s][pos]=mv;
      g_mvpos[s]=(pos+1)%LAGBUF;
      if(g_mvn[s]<LAGBUF) g_mvn[s]++;
      if(g_mvn[s]<1000){ okAll=false; continue; }
      double sum=0, sum2=0; int n=g_mvn[s];
      for(int k=0;k<n;k++){ sum+=g_mv[s][k]; sum2+=g_mv[s][k]*g_mv[s][k]; }
      double var = (sum2 - sum*sum/n)/MathMax(1,n-1);
      double sd = MathSqrt(MathMax(var,1e-18));
      z[s]= mv/sd;
   }
   if(!okAll) return;
   if(HavePosition()) return;
   if(TimeCurrent()-g_lastEntry < P.cooldownMin*60 && g_lastEntry>0) return;
   double basket = (z[0]+z[1]+z[2]+z[3])/4.0;
   int agree=0;
   for(int s=0;s<4;s++) if(z[s]*basket>0) agree++;
   if(agree<4) return;
   if(MathAbs(basket) < P.lagZ) return;
   if(MathAbs(z[4]) > P.lagUjz) return;
   int dir = (basket>0)? 1 : -1;
   if(dir>0) return;          // SHORT side only (long side negative in research)
   OpenDir(dir, 0);
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();

   // timed exit first (uses position open time — robust to EA reload)
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk>0 && PositionSelectByTicket(tk))
         if(PositionGetInteger(POSITION_MAGIC)==InpMagicBase+InpStrategyID
            && PositionGetString(POSITION_SYMBOL)==_Symbol
            && now - (datetime)PositionGetInteger(POSITION_TIME) >= P.holdMin*60)
            trade.PositionClose(tk);
   }

   if(P.family==3)
   {
      EvalLag(now);
   }
   else
   {
      // act once per new M1 bar
      datetime m1 = iTime(_Symbol, PERIOD_M1, 0);
      if(m1==g_lastM1) return;
      g_lastM1 = m1;
      if(P.family==2)
      {
         EvalCalendar(now);
         CheckBreakoutB();
      }
      else
      {
         EvalCoil(now);
         CheckBreakoutA();
      }
   }
   Comment(StringFormat("UJCoilLab id=%d fam=%d %s flag=%s r24n=%d",
           InpStrategyID, P.family, g_warmed?"ready":"warmup",
           g_flag?"ON":"off", g_r24n));
}

//+------------------------------------------------------------------+
double OnTester()
{
   double profit = TesterStatistics(STAT_PROFIT);
   double dd = TesterStatistics(STAT_BALANCE_DD);
   if(dd<=0) dd=1;
   return profit/dd;   // recovery factor
}
//+------------------------------------------------------------------+
