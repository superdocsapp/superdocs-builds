const path = require("path");
const fs = require("fs");

const OfficeAddinDevCerts = require("office-addin-dev-certs");

module.exports = async () => {
    const httpsOptions = await OfficeAddinDevCerts.getHttpsServerOptions();

    return {
        mode: "development",

        entry: {
            taskpane: "./taskpane.js"
        },

        output: {
            path: path.resolve(__dirname, "dist"),
            filename: "[name].bundle.js",
            clean: true
        },

        devServer: {
            host: "localhost",
            port: 3000,

            server: {
                type: "https",
                options: httpsOptions
            },

            static: {
                directory: path.resolve(__dirname)
            },

            headers: {
                "Access-Control-Allow-Origin": "*"
            },

            allowedHosts: "all",

            hot: true
        },

        module: {
            rules: [
                {
                    test: /\.css$/i,
                    use: [
                        "style-loader",
                        "css-loader"
                    ]
                }
            ]
        },

        resolve: {
            extensions: [".js", ".html"]
        }
    };
};