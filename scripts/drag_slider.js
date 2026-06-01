(function(){
  var el = document.querySelector('#nc_1_n1z');
  if(!el) return 'no slider';
  var rect = el.getBoundingClientRect();
  var sx = rect.x + rect.width / 2;
  var sy = rect.y + rect.height / 2;
  var totalDist = 240;
  var steps = [0.05,0.08,0.12,0.15,0.2,0.25,0.3,0.35,0.4,0.45,0.5,0.53,0.56,0.6,0.65,0.7,0.75,0.8,0.85,0.9,0.93,0.96,1.0];
  var evt = function(type,x,y){return new MouseEvent(type,{clientX:x,clientY:y,bubbles:true,cancelable:true});};
  el.dispatchEvent(evt('mousedown',sx,sy));
  for(var i=0;i<steps.length;i++){
    var cx = sx + totalDist*steps[i];
    var cy = sy + (Math.random()*4-2);
    document.dispatchEvent(evt('mousemove',cx,cy));
  }
  document.dispatchEvent(evt('mouseup',sx+totalDist,sy));
  return 'drag done from ' + sx + ',' + sy;
})();
