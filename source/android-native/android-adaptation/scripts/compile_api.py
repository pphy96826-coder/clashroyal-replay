"""Minimal compile-only API declarations, never included in classes.dex.

Offline prototype fallback. Android itself supplies implementations. Production
builds should pass an official SDK android.jar to build_apk.py instead.
"""
API={
'android.content.Context': '''public class Context {
 public java.io.File getFilesDir(){return null;} public android.content.ContentResolver getContentResolver(){return null;}
 public android.content.res.AssetManager getAssets(){return null;} public android.content.pm.PackageManager getPackageManager(){return null;}
 public void startActivity(android.content.Intent i){} public void startActivity(android.content.Intent i,android.os.Bundle options){}
 public android.content.ComponentName startForegroundService(android.content.Intent i){return null;}
 public Object getSystemService(String name){return null;}
 public android.content.ComponentName startService(android.content.Intent i){return null;} public boolean stopService(android.content.Intent i){return false;}
 public android.content.res.Resources getResources(){return null;} public Context getApplicationContext(){return this;}
}''',
'android.content.res.Resources': 'public class Resources {public android.util.DisplayMetrics getDisplayMetrics(){return null;}}',
'android.util.DisplayMetrics': 'public class DisplayMetrics {public int widthPixels,heightPixels; public float density;}',
'android.content.ComponentName': 'public class ComponentName {}',
'android.app.ActivityOptions': 'public class ActivityOptions {public static ActivityOptions makeBasic(){return null;} public ActivityOptions setLaunchBounds(android.graphics.Rect r){return this;} public android.os.Bundle toBundle(){return null;}}',
'android.graphics.Rect': 'public final class Rect {public Rect(int l,int t,int r,int b){}}',
'android.os.IBinder': 'public interface IBinder {}',
'android.R': 'public final class R {public static final class drawable {public static final int ic_media_play=17301540;}}',
'android.app.Service': '''public class Service extends android.content.Context {
 public static final int START_NOT_STICKY=2; public void onCreate(){}
 public int onStartCommand(android.content.Intent i,int f,int s){return 2;} public android.os.IBinder onBind(android.content.Intent i){return null;}
 public void startForeground(int id,Notification n){} public void stopForeground(boolean remove){} public void stopSelf(){}
 public void onDestroy(){}
}''',
'android.app.Notification': '''public class Notification {public PendingIntent contentIntent; public static class Builder {
 public Builder(android.content.Context c,String channel){} public Builder setSmallIcon(int id){return this;}
 public Builder setContentTitle(CharSequence t){return this;} public Builder setContentText(CharSequence t){return this;}
 public Builder setContentIntent(PendingIntent i){return this;} public Builder setOnlyAlertOnce(boolean v){return this;}
 public Builder setStyle(Style s){return this;}
 public Builder setOngoing(boolean v){return this;} public Notification build(){return null;}
} public static class Style {} public static class BigTextStyle extends Style {public BigTextStyle(){} public BigTextStyle bigText(CharSequence s){return this;}} }''',
'android.app.PendingIntent': 'public final class PendingIntent {public static final int FLAG_UPDATE_CURRENT=134217728,FLAG_IMMUTABLE=67108864; public static PendingIntent getActivity(android.content.Context c,int n,android.content.Intent i,int f){return null;} public static PendingIntent getService(android.content.Context c,int n,android.content.Intent i,int f){return null;} public String getCreatorPackage(){return null;}}',
'android.app.NotificationChannel': 'public class NotificationChannel {public NotificationChannel(String id,CharSequence name,int importance){}}',
'android.app.NotificationManager': 'public class NotificationManager {public static final int IMPORTANCE_LOW=2; public void createNotificationChannel(NotificationChannel c){} public void notify(int n,Notification v){}}',
'android.app.Activity': '''public class Activity extends android.content.Context {
 public static final int RESULT_OK=-1;
 public void onCreate(android.os.Bundle b){} protected void onActivityResult(int r,int s,android.content.Intent d){}
 protected void onDestroy(){} public void setTitle(CharSequence s){} public void setContentView(android.view.View v){}
 public void runOnUiThread(Runnable r){} public void startActivityForResult(android.content.Intent i,int n){}
 public android.content.Intent getIntent(){return null;} public void onBackPressed(){} public void finish(){}
 protected void onResume(){} protected void onPause(){}
}''',
'android.content.DialogInterface': 'public interface DialogInterface {public interface OnClickListener {void onClick(DialogInterface d,int w);}}',
'android.app.AlertDialog': '''public class AlertDialog {public static class Builder {public Builder(android.content.Context c){} public Builder setTitle(CharSequence s){return this;} public Builder setMessage(CharSequence s){return this;} public Builder setPositiveButton(CharSequence s,android.content.DialogInterface.OnClickListener l){return this;} public Builder setNegativeButton(CharSequence s,android.content.DialogInterface.OnClickListener l){return this;} public AlertDialog show(){return null;}}}''',
'android.content.Intent': '''public class Intent {
 public Intent(String a){} public Intent addCategory(String c){return this;} public Intent setType(String t){return this;}
 public Intent(android.content.Context c,Class<?> cls){} public Intent putExtra(String name,double value){return this;}
 public Intent putExtra(String name,String value){return this;} public Intent putExtra(String name,boolean value){return this;} public String getStringExtra(String k){return null;}
 public double getDoubleExtra(String name,double fallback){return fallback;}
 public Intent addFlags(int f){return this;} public android.net.Uri getData(){return null;}
 public Intent setData(android.net.Uri u){return this;}
 public Intent setAction(String a){return this;} public String getAction(){return null;}
}''',
'android.net.Uri': 'public class Uri { public String getScheme(){return null;} public String toString(){return "";} public static Uri parse(String s){return null;} }',
'android.provider.Settings': 'public final class Settings {public static final String ACTION_MANAGE_OVERLAY_PERMISSION="android.settings.action.MANAGE_OVERLAY_PERMISSION"; public static boolean canDrawOverlays(android.content.Context c){return false;}}',
'android.graphics.PixelFormat': 'public class PixelFormat {public static final int TRANSLUCENT=-3;}',
'android.view.Gravity': 'public class Gravity {public static final int TOP=48,CENTER_HORIZONTAL=1,LEFT=3,RIGHT=5,CENTER_VERTICAL=16,CENTER=17;}',
'android.view.WindowManager': '''public interface WindowManager {void addView(View v,ViewGroup.LayoutParams p); void removeView(View v); void updateViewLayout(View v,ViewGroup.LayoutParams p); public static class LayoutParams extends ViewGroup.LayoutParams {public static final int TYPE_APPLICATION_OVERLAY=2038,FLAG_NOT_FOCUSABLE=8,FLAG_NOT_TOUCHABLE=16,FLAG_NOT_TOUCH_MODAL=32; public int gravity,x,y; public float alpha; public LayoutParams(int w,int h,int t,int f,int format){super(w,h);}}}''',
'android.net.ConnectivityManager': 'public class ConnectivityManager {public ProxyInfo getDefaultProxy(){return null;}}',
'android.net.ProxyInfo': 'public class ProxyInfo {public String getHost(){return null;} public int getPort(){return 0;} public Uri getPacFileUrl(){return null;}}',
'android.net.http.SslError': 'public class SslError {}',
'android.content.ContentResolver': 'public class ContentResolver {public java.io.InputStream openInputStream(android.net.Uri u)throws java.io.FileNotFoundException{return null;} public java.io.OutputStream openOutputStream(android.net.Uri u,String mode)throws java.io.FileNotFoundException{return null;}}',
'android.content.res.AssetManager': 'public class AssetManager {public java.io.InputStream open(String n)throws java.io.IOException{return null;}}',
'android.content.pm.PackageManager': 'public class PackageManager {public android.content.Intent getLaunchIntentForPackage(String p){return null;} public PackageInfo getPackageInfo(String p,int f)throws NameNotFoundException{return null;} public ApplicationInfo getApplicationInfo(String p,int f)throws NameNotFoundException{return null;} public static class NameNotFoundException extends Exception {}}',
'android.content.pm.PackageInfo': 'public class PackageInfo {public String versionName;}',
'android.content.pm.ApplicationInfo': 'public class ApplicationInfo {public String sourceDir; public String nativeLibraryDir;}',
'android.os.Bundle': 'public class Bundle {public void putString(String k,String v){} }',
'android.os.Handler': 'public class Handler {public Handler(){} public boolean post(Runnable r){return true;} public boolean postDelayed(Runnable r,long ms){return true;} public void removeCallbacks(Runnable r){} }',
'android.view.View': '''public class View {
 public View(android.content.Context c){} public void setPadding(int l,int t,int r,int b){} public void setBackgroundColor(int c){}
 public static final int VISIBLE=0,GONE=8; public void setVisibility(int v){}
 public void setEnabled(boolean e){} public void setOnClickListener(OnClickListener l){}
 public interface OnClickListener {void onClick(View v);}
 public void setOnTouchListener(OnTouchListener l){} public interface OnTouchListener {boolean onTouch(View v,MotionEvent e);}
 public void setAlpha(float a){} public void setBackground(android.graphics.drawable.Drawable d){} public void setMinimumHeight(int h){} public void setMinimumWidth(int w){}
 public void setLayoutParams(ViewGroup.LayoutParams p){}
}''',
'android.view.MotionEvent': 'public final class MotionEvent {public static final int ACTION_DOWN=0,ACTION_UP=1,ACTION_MOVE=2,ACTION_CANCEL=3; public int getAction(){return 0;} public float getRawX(){return 0;} public float getRawY(){return 0;}}',
'android.graphics.drawable.Drawable': 'public abstract class Drawable {}',
'android.graphics.drawable.GradientDrawable': 'public class GradientDrawable extends Drawable {public GradientDrawable(){} public void setColor(int c){} public void setCornerRadius(float r){} public void setStroke(int w,int c){}}',
'android.view.ViewGroup': 'public class ViewGroup extends View {public ViewGroup(android.content.Context c){super(c);} public void addView(View v){} public void addView(View v,LayoutParams p){} public void removeAllViews(){} public static class LayoutParams {public int width,height; public LayoutParams(int w,int h){}} public static class MarginLayoutParams extends LayoutParams {public MarginLayoutParams(int w,int h){super(w,h);} public void setMargins(int l,int t,int r,int b){}} }',
'android.widget.LinearLayout': 'public class LinearLayout extends android.view.ViewGroup {public LinearLayout(android.content.Context c){super(c);} public void setOrientation(int o){} public void setGravity(int g){} public static class LayoutParams extends android.view.ViewGroup.MarginLayoutParams {public LayoutParams(int w,int h){super(w,h);} public LayoutParams(int w,int h,float weight){super(w,h);}} }',
'android.widget.ScrollView': 'public class ScrollView extends android.view.ViewGroup {public ScrollView(android.content.Context c){super(c);} }',
'android.widget.TextView': 'public class TextView extends android.view.View {public TextView(android.content.Context c){super(c);} public void setText(CharSequence t){} public void setTextSize(float s){} public void setTextColor(int c){} public void setGravity(int g){} public void setMaxLines(int n){} public void setSingleLine(boolean v){} public void setMinHeight(int h){} public void setMinWidth(int w){} public void setAllCaps(boolean v){} }',
'android.widget.Button': 'public class Button extends TextView {public Button(android.content.Context c){super(c);} }',
'android.text.Editable': 'public interface Editable extends CharSequence {}',
'android.widget.EditText': 'public class EditText extends TextView {public EditText(android.content.Context c){super(c);}public android.text.Editable getText(){return null;}}',
'android.graphics.Bitmap': 'public class Bitmap {}',
'android.webkit.ValueCallback': 'public interface ValueCallback<T> {void onReceiveValue(T value);}',
'android.webkit.SslErrorHandler': 'public class SslErrorHandler {public void cancel(){}}',
'android.webkit.WebResourceRequest': 'public interface WebResourceRequest {android.net.Uri getUrl(); boolean isForMainFrame();}',
'android.webkit.WebResourceError': 'public abstract class WebResourceError {public abstract CharSequence getDescription();}',
'android.webkit.WebResourceResponse': 'public class WebResourceResponse {public WebResourceResponse(String type,String encoding,java.io.InputStream in){}}',
'android.webkit.WebSettings': '''public abstract class WebSettings {public static final int MIXED_CONTENT_NEVER_ALLOW=1; public abstract void setBlockNetworkLoads(boolean v); public abstract void setAllowFileAccess(boolean v); public abstract void setAllowContentAccess(boolean v); public abstract void setAllowFileAccessFromFileURLs(boolean v); public abstract void setAllowUniversalAccessFromFileURLs(boolean v); public abstract void setMixedContentMode(int v); public abstract void setJavaScriptCanOpenWindowsAutomatically(boolean v); public abstract void setSupportMultipleWindows(boolean v); public abstract void setJavaScriptEnabled(boolean v); public abstract void setDomStorageEnabled(boolean v);}''',
'android.webkit.WebViewClient': '''public class WebViewClient {public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return false;} public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){return null;} public void onPageStarted(WebView v,String u,android.graphics.Bitmap i){} public void onPageFinished(WebView v,String u){} public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){} public void onReceivedSslError(WebView v,SslErrorHandler h,android.net.http.SslError e){}}''',
'android.webkit.WebView': '''public class WebView extends android.widget.AbsoluteLayout {public WebView(android.content.Context c){super(c);} public WebSettings getSettings(){return null;} public void setWebViewClient(WebViewClient c){} public void loadUrl(String u){} public String getUrl(){return null;} public void evaluateJavascript(String s,ValueCallback<String> c){} public boolean canGoBack(){return false;} public void goBack(){} public void stopLoading(){} public void destroy(){}}''',
'android.widget.AbsoluteLayout': 'public class AbsoluteLayout extends android.view.ViewGroup {public AbsoluteLayout(android.content.Context c){super(c);}}',
'android.app.Instrumentation': 'public class Instrumentation {public void onCreate(android.os.Bundle b){} public void onStart(){} public void start(){} public android.content.Context getTargetContext(){return null;} public void finish(int r,android.os.Bundle b){} }',
'org.json.JSONException': 'public class JSONException extends Exception {public JSONException(String m){super(m);} }',
'org.json.JSONArray': '''public class JSONArray {
 public JSONArray(){} public JSONArray(String s)throws JSONException{} public int length(){return 0;}
 public JSONObject getJSONObject(int i)throws JSONException{return null;} public JSONObject optJSONObject(int i){return null;} public JSONArray put(Object v){return this;}
 public String toString(){return "";}
}''',
'org.json.JSONObject': '''public class JSONObject {
 public JSONObject(){} public JSONObject(String s)throws JSONException{} public JSONObject put(String k,Object v)throws JSONException{return this;}
 public String getString(String k)throws JSONException{return null;} public boolean optBoolean(String k,boolean d){return d;}
 public long optLong(String k,long d){return d;} public String optString(String k,String d){return d;} public String toString(){return "{}";}
 public JSONObject getJSONObject(String k)throws JSONException{return null;} public JSONObject optJSONObject(String k){return null;}
 public java.util.Iterator<String> keys(){return null;}
}'''
}
