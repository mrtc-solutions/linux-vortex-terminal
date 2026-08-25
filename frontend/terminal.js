/*
 * Small dependency-free terminal buffer for the local PTY preview.
 *
 * It deliberately implements the terminal controls Vortex emits/accepts:
 * SGR, cursor movement, erase, insert/delete, save/restore, margins, and
 * alternate screen. Input remains owned by the Python PTY; this renderer never
 * interprets output as HTML or executes terminal control strings.
 */
class VortexTerminal {
  constructor(cols = 100, rows = 30, scrollbackLimit = 5000) {
    this.cols = Math.max(2, cols); this.rows = Math.max(2, rows); this.scrollbackLimit = scrollbackLimit;
    this.primary = this.makeScreen(); this.alternate = this.makeScreen(); this.useAlternate = false;
    this.cursor = {x:0, y:0, visible:true}; this.saved = {x:0, y:0, style:this.defaultStyle()};
    this.style = this.defaultStyle(); this.scrollback = []; this.state = 'normal'; this.csi = ''; this.osc = '';
    this.topMargin = 0; this.bottomMargin = this.rows - 1;
  }
  defaultStyle() { return {fg:null, bg:null, bold:false, inverse:false}; }
  blankCell() { return {ch:' ', ...this.defaultStyle()}; }
  makeScreen() { return Array.from({length:this.rows}, () => Array.from({length:this.cols}, () => this.blankCell())); }
  screen() { return this.useAlternate ? this.alternate : this.primary; }
  reset() { this.primary=this.makeScreen(); this.alternate=this.makeScreen(); this.useAlternate=false; this.scrollback=[]; this.cursor={x:0,y:0,visible:true}; this.saved={x:0,y:0,style:this.defaultStyle()}; this.style=this.defaultStyle(); this.topMargin=0; this.bottomMargin=this.rows-1; this.state='normal'; this.csi=''; this.osc=''; }
  resize(cols, rows) {
    cols=Math.max(2, Math.min(500, Number(cols)||this.cols)); rows=Math.max(2, Math.min(500, Number(rows)||this.rows));
    if (cols===this.cols && rows===this.rows) return;
    const resizeScreen=(old)=>Array.from({length:rows},(_,y)=>Array.from({length:cols},(_,x)=>old[y]?.[x]||this.blankCell()));
    this.primary=resizeScreen(this.primary); this.alternate=resizeScreen(this.alternate); this.cols=cols; this.rows=rows; this.bottomMargin=rows-1; this.cursor.x=Math.min(this.cursor.x,cols-1); this.cursor.y=Math.min(this.cursor.y,rows-1);
  }
  clamp() { this.cursor.x=Math.max(0,Math.min(this.cols-1,this.cursor.x)); this.cursor.y=Math.max(0,Math.min(this.rows-1,this.cursor.y)); }
  pushScroll(row) { if (!this.useAlternate) { this.scrollback.push(row.map(cell=>({...cell}))); if (this.scrollback.length>this.scrollbackLimit) this.scrollback.splice(0,this.scrollback.length-this.scrollbackLimit); } }
  lineFeed() { if (this.cursor.y===this.bottomMargin) { const line=this.screen().splice(this.topMargin,1)[0]; this.screen().splice(this.bottomMargin,0,Array.from({length:this.cols},()=>this.blankCell())); this.pushScroll(line); } else this.cursor.y=Math.min(this.bottomMargin,this.cursor.y+1); }
  put(ch) { if (ch==='\n') { this.lineFeed(); return; } if (ch==='\r') { this.cursor.x=0; return; } if (ch==='\b') { this.cursor.x=Math.max(0,this.cursor.x-1); return; } if (ch==='\t') { this.cursor.x=Math.min(this.cols-1,Math.ceil((this.cursor.x+1)/8)*8); return; } if (ch<' ' || ch==='\x7f') return; this.screen()[this.cursor.y][this.cursor.x]={ch,...this.style}; if (this.cursor.x===this.cols-1) { this.cursor.x=0; this.lineFeed(); } else this.cursor.x++; }
  params() { const privateMode=this.csi.startsWith('?'); const raw=privateMode?this.csi.slice(1):this.csi; const values=raw===''?[]:raw.split(';').map(item=>{const n=parseInt(item,10);return Number.isFinite(n)?n:0}); return {privateMode, values}; }
  n(values,index=0, fallback=1) { return values[index] || fallback; }
  eraseLine(mode) { const line=this.screen()[this.cursor.y]; const start=mode===1?0:this.cursor.x; const end=mode===1?this.cursor.x:this.cols-1; if(mode===2){for(let x=0;x<this.cols;x++)line[x]=this.blankCell();return;} for(let x=start;x<=end;x++)line[x]=this.blankCell(); }
  eraseDisplay(mode) { const screen=this.screen(); if(mode===2||mode===3){for(let y=0;y<this.rows;y++)for(let x=0;x<this.cols;x++)screen[y][x]=this.blankCell(); if(mode===3)this.scrollback=[];return;} if(mode===0){this.eraseLine(0);for(let y=this.cursor.y+1;y<this.rows;y++)screen[y]=Array.from({length:this.cols},()=>this.blankCell());}else if(mode===1){this.eraseLine(1);for(let y=0;y<this.cursor.y;y++)screen[y]=Array.from({length:this.cols},()=>this.blankCell());} }
  moveLines(count, insert) { const screen=this.screen(); const y=this.cursor.y; for(let i=0;i<count;i++){if(insert){screen.splice(y,0,Array.from({length:this.cols},()=>this.blankCell()));screen.splice(this.bottomMargin+1,1);}else{screen.splice(y,1);screen.splice(this.bottomMargin,0,Array.from({length:this.cols},()=>this.blankCell()));}} }
  sgr(values) { if(!values.length)values=[0]; for(let i=0;i<values.length;i++){const code=values[i];if(code===0)this.style=this.defaultStyle();else if(code===1)this.style.bold=true;else if(code===22)this.style.bold=false;else if(code===7)this.style.inverse=true;else if(code===27)this.style.inverse=false;else if(code===39)this.style.fg=null;else if(code===49)this.style.bg=null;else if(code>=30&&code<=37)this.style.fg=code-30;else if(code>=90&&code<=97)this.style.fg=code-90+8;else if(code>=40&&code<=47)this.style.bg=code-40;else if(code>=100&&code<=107)this.style.bg=code-100+8;else if(code===38&&values[i+1]===5&&Number.isFinite(values[i+2])){this.style.fg=values[i+2]%16;i+=2;}else if(code===48&&values[i+1]===5&&Number.isFinite(values[i+2])){this.style.bg=values[i+2]%16;i+=2;} } }
  csiFinal(final) { const {privateMode,values}=this.params(); const amount=this.n(values); switch(final){
    case 'A':this.cursor.y-=amount;break; case 'B':case 'e':this.cursor.y+=amount;break; case 'C':case 'a':this.cursor.x+=amount;break; case 'D':this.cursor.x-=amount;break; case 'E':this.cursor.y+=amount;this.cursor.x=0;break; case 'F':this.cursor.y-=amount;this.cursor.x=0;break; case 'G':case '`':this.cursor.x=this.n(values)-1;break; case 'd':this.cursor.y=this.n(values)-1;break;
    case 'H':case 'f':this.cursor.y=(values[0]||1)-1;this.cursor.x=(values[1]||1)-1;break; case 'J':this.eraseDisplay(values[0]||0);break; case 'K':this.eraseLine(values[0]||0);break; case 'm':this.sgr(values);break; case 's':this.saved={x:this.cursor.x,y:this.cursor.y,style:{...this.style}};break; case 'u':this.cursor.x=this.saved.x;this.cursor.y=this.saved.y;this.style={...this.saved.style};break;
    case 'h':case 'l':if(privateMode){for(const value of values){if(value===25)this.cursor.visible=final==='h';if(value===47||value===1047||value===1049){if(final==='h'){this.useAlternate=true;this.alternate=this.makeScreen();this.cursor.x=0;this.cursor.y=0;}else{this.useAlternate=false;this.cursor.x=0;this.cursor.y=0;}}}}break;
    case 'r':this.topMargin=Math.max(0,(values[0]||1)-1);this.bottomMargin=Math.min(this.rows-1,(values[1]||this.rows)-1);this.cursor.x=0;this.cursor.y=this.topMargin;break; case '@':{const line=this.screen()[this.cursor.y],count=Math.min(amount,this.cols-this.cursor.x);for(let x=this.cols-1;x>=this.cursor.x+count;x--)line[x]=line[x-count];for(let x=0;x<count;x++)line[this.cursor.x+x]=this.blankCell();break;} case 'P':{const line=this.screen()[this.cursor.y],count=Math.min(amount,this.cols-this.cursor.x);for(let x=this.cursor.x;x<this.cols-count;x++)line[x]=line[x+count];for(let x=this.cols-count;x<this.cols;x++)line[x]=this.blankCell();break;} case 'X':{const line=this.screen()[this.cursor.y];for(let x=this.cursor.x;x<Math.min(this.cols,this.cursor.x+amount);x++)line[x]=this.blankCell();break;} case 'L':this.moveLines(amount,true);break; case 'M':this.moveLines(amount,false);break;
  } this.clamp(); }
  feed(data) { for(const ch of String(data)){if(this.state==='osc'){if(ch==='\x07'){this.state='normal';this.osc='';}else if(ch==='\x1b'){this.state='osc-st';}else this.osc+=ch;continue;}if(this.state==='osc-st'){if(ch==='\\')this.state='normal';else this.state='osc';continue;}if(this.state==='esc'){if(ch==='['){this.state='csi';this.csi='';}else if(ch===']'){this.state='osc';this.osc='';}else if(ch==='7'){this.saved={x:this.cursor.x,y:this.cursor.y,style:{...this.style}};this.state='normal';}else if(ch==='8'){this.cursor.x=this.saved.x;this.cursor.y=this.saved.y;this.style={...this.saved.style};this.state='normal';}else if(ch==='D'){this.lineFeed();this.state='normal';}else if(ch==='M'){if(this.cursor.y===this.topMargin){this.screen().splice(this.topMargin,0,Array.from({length:this.cols},()=>this.blankCell()));this.screen().splice(this.bottomMargin+1,1);}else this.cursor.y--;this.state='normal';}else if(ch==='E'){this.cursor.x=0;this.lineFeed();this.state='normal';}else if(ch==='c'){this.reset();}else this.state='normal';continue;}if(this.state==='csi'){if(ch>='@'&&ch<='~'){this.csiFinal(ch);this.csi='';this.state='normal';}else this.csi+=ch;continue;}if(ch==='\x1b'){this.state='esc';continue;}if(ch==='\x07')continue;this.put(ch);} }
  styleClass(cell){let fg=cell.fg===null?'':`ansi-color-${cell.fg}`;let bg=cell.bg===null?'':`ansi-bg-${cell.bg}`;return `${fg} ${bg} ${cell.bold?'ansi-bold':''} ${cell.inverse?'ansi-inverse':''}`.trim();}
  esc(text){return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
  render(element){let html='';for(let y=0;y<this.rows;y++){let line=this.screen()[y],open='';for(const cell of line){const cls=this.styleClass(cell);if(cls!==open){if(open)html+='</span>';if(cls)html+=`<span class="${cls}">`;open=cls;}html+=this.esc(cell.ch);}if(open)html+='</span>';if(y<this.rows-1)html+='\n';}element.innerHTML=html;element.dataset.cursorVisible=this.cursor.visible?'true':'false';element.scrollTop=element.scrollHeight;}
}
window.VortexTerminal = VortexTerminal;
