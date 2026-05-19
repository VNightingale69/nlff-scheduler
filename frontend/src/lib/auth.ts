'use client';
export const getToken=()=>typeof window==='undefined'?'':localStorage.getItem('access_token')||'';
export const setTokens=(a:string,r:string)=>{localStorage.setItem('access_token',a);localStorage.setItem('refresh_token',r)};
export const clearTokens=()=>{localStorage.removeItem('access_token');localStorage.removeItem('refresh_token')};
