import { describe, expect, it } from 'vitest';
import { memberships, parseNumeric } from './api';
import type { Boundary } from './api';

const feature:Boundary={type:'Feature',id:'hole',properties:{id:'hole',name_fa:'test',name_normalized:'test',district_no:1,quality_flags:[]},geometry:{type:'Polygon',coordinates:[[[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]]]}};
describe('frontend spatial and numeric contracts',()=>{
  it('keeps points outside holes and reports overlapping membership',()=>{
    expect(memberships(0.5,0.5,[feature])).toEqual(['hole']);
    expect(memberships(2,2,[feature])).toEqual([]);
    expect(memberships(0.5,0.5,[feature,{...feature,id:'second'}])).toEqual(['hole','second']);
  });
  it('supports MultiPolygon and lon-lat coordinate order',()=>{
    const multi:Boundary={...feature,id:'multi',geometry:{type:'MultiPolygon',coordinates:[[[[51,35],[52,35],[52,36],[51,36],[51,35]]],[[[53,35],[54,35],[54,36],[53,36],[53,35]]]]}};
    expect(memberships(53.5,35.5,[multi])).toEqual(['multi']);
    expect(memberships(35.5,53.5,[multi])).toEqual([]);
  });
  it('preserves null and parses all supported digit sets',()=>{
    expect(parseNumeric('')).toBeNull();
    expect(parseNumeric('۱۲٬۰۰۰')).toBe(12000);
    expect(parseNumeric('١٢٫٥')).toBe(12.5);
    expect(()=>parseNumeric('abc')).toThrow();
  });
});
