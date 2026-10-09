import { createContext, useContext } from 'react';
export const DesktopContext = createContext(null);
export const useDesktop = () => useContext(DesktopContext);
