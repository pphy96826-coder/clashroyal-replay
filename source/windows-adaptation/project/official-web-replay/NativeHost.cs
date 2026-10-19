using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Collections.Generic;

class NativeHost {
    static string Quote(string s) {
        if (s.IndexOfAny(new char[]{'"','\r','\n'})>=0 || s.EndsWith("\\")) throw new Exception("Invalid launch argument");
        return "\""+s+"\"";
    }
    static int Main(string[] args) {
        try {
            string root=AppDomain.CurrentDomain.BaseDirectory;
            var config=new JavaScriptSerializer().Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(root,"host-launch.json")));
            var info=new ProcessStartInfo(config["python"]);
            info.Arguments="-X utf8 "+Quote(config["script"]);
            foreach (string arg in args) info.Arguments+=" "+Quote(arg);
            info.UseShellExecute=false; info.CreateNoWindow=true;
            info.RedirectStandardInput=true; info.RedirectStandardOutput=true; info.RedirectStandardError=true;
            info.WorkingDirectory=Path.GetDirectoryName(config["script"]);
            info.EnvironmentVariables["PYTHONUTF8"]="1";
            using (var child=Process.Start(info)) {
                Task.Run(()=>{try {
                    var input=Console.OpenStandardInput();var output=child.StandardInput.BaseStream;
                    byte[] buffer=new byte[8192];int count;
                    while ((count=input.Read(buffer,0,buffer.Length))>0) {output.Write(buffer,0,count);output.Flush();}
                    child.StandardInput.Close();
                }catch{}});
                Task.Run(()=>{try {child.StandardError.BaseStream.CopyTo(Console.OpenStandardError());}catch{}});
                child.StandardOutput.BaseStream.CopyTo(Console.OpenStandardOutput());
                child.WaitForExit(); return child.ExitCode;
            }
        } catch (Exception error) {Console.Error.WriteLine(error.Message);return 1;}
    }
}
