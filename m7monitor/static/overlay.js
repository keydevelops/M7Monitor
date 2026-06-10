function rangeClass(value, stale, disableColors){
  if(disableColors) return 'plain';
  if(stale) return 'stale';
  if(value >= 120) return 'red';
  if(value >= 90) return 'yellow';
  return 'green';
}

function setMeta(s, text){
  const meta=document.getElementById('meta');
  const shouldShow=s.settings?.debug || ['connecting','authenticating'].includes(s.status);
  meta.textContent=shouldShow ? text : '';
  meta.classList.toggle('hidden', !shouldShow);
}

async function tick(){
  try{
    const s=await fetch('/api/state',{cache:'no-store'}).then(r=>r.json());
    const box=document.getElementById('box');
    const hr=document.getElementById('hr');

    if(s.heart_rate){
      hr.textContent=s.heart_rate.value;
      box.className='box '+rangeClass(s.heart_rate.value, s.heart_rate.stale, !!s.settings?.disableColors);
      setMeta(s, `${s.status} • ${s.heart_rate.source||''} • ${s.heart_rate.age_seconds}s ago`);
    }else{
      hr.textContent='--';
      box.className='box '+(s.settings?.disableColors?'plain':'err');
      setMeta(s, s.status+(s.last_error?' • '+s.last_error:''));
    }
  }catch(e){
    document.getElementById('hr').textContent='--';
    setMeta({settings:{debug:true},status:'offline'}, 'server offline');
  }
}

tick(); setInterval(tick, 800);
