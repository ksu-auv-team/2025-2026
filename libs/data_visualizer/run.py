from create_app import create_app

if __name__ == "__main__":
    app = create_app()

    # should use a config file to set these
    #
    # these are default varibles
    app.run(host="0.0.0.0", port=5002, debug=True, threaded=True)

