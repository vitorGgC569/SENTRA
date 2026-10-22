const path=require('node:path');
const {getDefaultConfig}=require('expo/metro-config');
const config=getDefaultConfig(__dirname);
config.watchFolders=[path.resolve(__dirname,'../transport')];
config.resolver.nodeModulesPaths=[path.resolve(__dirname,'node_modules'),path.resolve(__dirname,'../transport/node_modules')];
module.exports=config;
